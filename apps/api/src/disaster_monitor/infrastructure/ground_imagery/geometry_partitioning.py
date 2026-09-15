"""Deterministic image-grid partition plans for difficult WGS84 regions."""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import StrEnum
from math import floor
from typing import Any

from shapely.geometry import box, mapping, shape
from shapely.ops import transform

from disaster_monitor.domain.imagery.regions import MultiPolygon, polygon_from_geojson


class GeometryPartitionKind(StrEnum):
    SINGLE_GRID = "single_grid"
    ANTIMERIDIAN = "antimeridian"
    POLAR = "polar"
    MULTI_UTM_ZONE = "multi_utm_zone"


@dataclass(frozen=True, slots=True)
class GeometryPartition:
    partition_id: str
    geometry: MultiPolygon
    grid_crs: str
    merge_order: int


@dataclass(frozen=True, slots=True)
class GeometryPartitionPlan:
    kind: GeometryPartitionKind
    parts: tuple[GeometryPartition, ...]
    merge_rule: str


def partition_geometry(geometry: MultiPolygon) -> GeometryPartitionPlan:
    source = shape(geometry.as_geojson())
    min_lon, min_lat, max_lon, max_lat = geometry.bounds
    if _crosses_antimeridian(geometry):
        shifted = transform(lambda x, y, z=None: ((x + 360) % 360, y), source)
        pieces = []
        for index, clip in enumerate((box(0, -90, 180, 90), box(180, -90, 360, 90))):
            piece = shifted.intersection(clip)
            if piece.is_empty:
                continue
            if index == 1:
                piece = transform(lambda x, y, z=None: (x - 360, y), piece)
            pieces.append(
                _part(
                    piece, _utm_or_polar_crs(piece.centroid.y, piece.centroid.x), index
                )
            )
        return GeometryPartitionPlan(
            GeometryPartitionKind.ANTIMERIDIAN,
            tuple(pieces),
            "source-order mosaic with a -180/180 wrap seam; nodata never "
            "overwrites data",
        )
    if max_lat >= 84 or min_lat <= -80:
        crs = "EPSG:32661" if max_lat >= 84 else "EPSG:32761"
        return GeometryPartitionPlan(
            GeometryPartitionKind.POLAR,
            (_part(source, crs, 0),),
            "single UPS grid",
        )
    first_zone = _utm_zone(min_lon)
    last_zone = _utm_zone(max_lon)
    if first_zone != last_zone:
        parts: list[GeometryPartition] = []
        order = 0
        for zone in range(first_zone, last_zone + 1):
            left = -180 + (zone - 1) * 6
            piece = source.intersection(box(left, -80, left + 6, 84))
            if piece.is_empty:
                continue
            hemisphere = 32600 if piece.centroid.y >= 0 else 32700
            parts.append(_part(piece, f"EPSG:{hemisphere + zone}", order))
            order += 1
        return GeometryPartitionPlan(
            GeometryPartitionKind.MULTI_UTM_ZONE,
            tuple(parts),
            "ascending UTM-zone mosaic on a shared WGS84 display grid",
        )
    return GeometryPartitionPlan(
        GeometryPartitionKind.SINGLE_GRID,
        (_part(source, _utm_or_polar_crs(source.centroid.y, source.centroid.x), 0),),
        "single grid",
    )


def _crosses_antimeridian(geometry: MultiPolygon) -> bool:
    return any(
        abs(first.longitude - second.longitude) > 180
        for polygon in geometry.polygons
        for ring in (polygon.exterior, *polygon.holes)
        for first, second in zip(ring.coordinates, ring.coordinates[1:], strict=False)
    )


def _utm_zone(longitude: float) -> int:
    return min(60, max(1, floor((longitude + 180) / 6) + 1))


def _utm_or_polar_crs(latitude: float, longitude: float) -> str:
    if latitude >= 84:
        return "EPSG:32661"
    if latitude <= -80:
        return "EPSG:32761"
    base = 32600 if latitude >= 0 else 32700
    return f"EPSG:{base + _utm_zone(longitude)}"


def _part(value: Any, crs: str, order: int) -> GeometryPartition:
    document = json.loads(json.dumps(mapping(value)))
    geometry = polygon_from_geojson(document)
    return GeometryPartition(
        partition_id=f"imagery-part:{order}:{geometry.sha256()[:16]}",
        geometry=geometry,
        grid_crs=crs,
        merge_order=order,
    )


__all__ = [
    "GeometryPartition",
    "GeometryPartitionKind",
    "GeometryPartitionPlan",
    "partition_geometry",
]
