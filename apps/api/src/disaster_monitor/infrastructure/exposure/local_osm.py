"""Reproducible critical-infrastructure queries over a local OSM GeoJSON extract."""

import json
from collections.abc import Callable
from datetime import UTC, datetime
from math import asin, cos, radians, sin, sqrt
from pathlib import Path
from typing import cast

from disaster_monitor.domain.exposure import (
    ExposureGeometry,
    InfrastructureAsset,
    InfrastructureCategory,
    OsmCompletenessIndicator,
    OsmCompletenessQuality,
)
from disaster_monitor.domain.imagery.regions import (
    Coordinate,
    contains_coordinate,
    geometries_intersect,
    path_intersects_geometry,
    polygon_from_geojson,
)

_AMENITIES = {
    "hospital": InfrastructureCategory.HOSPITAL,
    "clinic": InfrastructureCategory.CLINIC,
    "school": InfrastructureCategory.SCHOOL,
    "fire_station": InfrastructureCategory.FIRE_STATION,
    "police": InfrastructureCategory.POLICE,
    "shelter": InfrastructureCategory.SHELTER,
}
_MAJOR_ROADS = {"motorway", "trunk", "primary", "secondary"}


class LocalOsmAssetExposure:
    def __init__(
        self,
        extract_path: Path,
        *,
        extract_version: str,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        if not extract_path.is_file() or not extract_version.strip():
            raise ValueError("A local OSM extract and version are required.")
        self._path = extract_path
        self._version = extract_version
        self._clock = clock

    async def intersecting_assets(
        self, geometry: ExposureGeometry
    ) -> tuple[InfrastructureAsset, ...]:
        document = self._document()
        features = cast(list[object], document["features"])
        results = []
        for raw in features:
            asset = _asset(raw, self._version)
            if asset is not None and _intersects(asset, geometry):
                results.append(asset)
        return tuple(sorted(results, key=lambda item: item.asset_id))

    async def completeness(
        self, geometry: ExposureGeometry
    ) -> OsmCompletenessIndicator:
        document = self._document()
        metadata = document.get("metadata")
        if not isinstance(metadata, dict) or not metadata.get("source_updated_at"):
            raise ValueError(
                "OSM completeness requires explicit source_updated_at metadata."
            )
        source_updated_at = _timestamp(str(metadata["source_updated_at"]))
        assets: list[tuple[InfrastructureAsset, bool]] = []
        for raw in cast(list[object], document["features"]):
            asset = _asset(raw, self._version)
            if asset is None or not _intersects(asset, geometry):
                continue
            properties = raw.get("properties") if isinstance(raw, dict) else None
            named = (
                bool(properties.get("name")) if isinstance(properties, dict) else False
            )
            assets.append((asset, named))
        area = _bbox_area_km2(geometry)
        road_length = sum(
            _path_length_km(asset.path)
            for asset, _ in assets
            if asset.category is InfrastructureCategory.MAJOR_ROAD
        )
        facility_count = sum(
            asset.category
            not in {InfrastructureCategory.MAJOR_ROAD, InfrastructureCategory.BRIDGE}
            for asset, _ in assets
        )
        count = len(assets)
        named_fraction = sum(named for _, named in assets) / count if count else None
        quality = (
            OsmCompletenessQuality.GOOD
            if count >= 100 and (named_fraction or 0) >= 0.7
            else OsmCompletenessQuality.LIMITED
            if count
            else OsmCompletenessQuality.POOR
        )
        return OsmCompletenessIndicator(
            dataset_id="openstreetmap-local",
            dataset_version=self._version,
            source_updated_at=source_updated_at,
            calculated_at=self._clock(),
            mapped_feature_count=count,
            named_feature_fraction=named_fraction,
            road_density_km_per_sq_km=road_length / area if area else None,
            critical_facility_density_per_sq_km=(
                facility_count / area if area else None
            ),
            quality=quality,
            limitation=(
                "Mapping density, named-feature fraction, and source age are proxies, "
                "not proof of OpenStreetMap completeness or real-world absence."
            ),
        )

    def _document(self) -> dict[str, object]:
        document = json.loads(self._path.read_text(encoding="utf-8"))
        if (
            not isinstance(document, dict)
            or document.get("type") != "FeatureCollection"
        ):
            raise ValueError(
                "The local OSM extract must be a GeoJSON FeatureCollection."
            )
        features = document.get("features")
        if not isinstance(features, list) or len(features) > 1_000_000:
            raise ValueError(
                "The local OSM extract feature list is invalid or unbounded."
            )
        return document


def _asset(raw: object, version: str) -> InfrastructureAsset | None:
    if not isinstance(raw, dict) or not isinstance(raw.get("properties"), dict):
        return None
    properties = raw["properties"]
    category = _category(properties)
    raw_geometry = raw.get("geometry")
    if category is None or not isinstance(raw_geometry, dict):
        return None
    asset_id = str(raw.get("id") or properties.get("osm_id") or "").strip()
    name = str(properties.get("name") or category.value.replace("_", " ")).strip()
    geometry_type = raw_geometry.get("type")
    coordinates = raw_geometry.get("coordinates")
    try:
        if (
            geometry_type == "Point"
            and isinstance(coordinates, list)
            and len(coordinates) >= 2
        ):
            return InfrastructureAsset(
                asset_id=asset_id,
                name=name,
                category=category,
                source_dataset_id="openstreetmap-local",
                source_version=version,
                coordinate=Coordinate(float(coordinates[1]), float(coordinates[0])),
            )
        if geometry_type in {"Polygon", "MultiPolygon"}:
            return InfrastructureAsset(
                asset_id=asset_id,
                name=name,
                category=category,
                source_dataset_id="openstreetmap-local",
                source_version=version,
                geometry=polygon_from_geojson(raw_geometry),
            )
        if geometry_type == "LineString" and isinstance(coordinates, list):
            return InfrastructureAsset(
                asset_id=asset_id,
                name=name,
                category=category,
                source_dataset_id="openstreetmap-local",
                source_version=version,
                path=tuple(
                    Coordinate(float(item[1]), float(item[0])) for item in coordinates
                ),
            )
    except (TypeError, ValueError, IndexError):
        return None
    return None


def _category(properties: dict[str, object]) -> InfrastructureCategory | None:
    amenity = str(properties.get("amenity") or "")
    if amenity in _AMENITIES:
        return _AMENITIES[amenity]
    if str(properties.get("emergency") or "") == "shelter":
        return InfrastructureCategory.SHELTER
    if str(properties.get("bridge") or "") not in {"", "no"}:
        return InfrastructureCategory.BRIDGE
    if str(properties.get("highway") or "") in _MAJOR_ROADS:
        return InfrastructureCategory.MAJOR_ROAD
    if str(properties.get("power") or "") in {"plant", "substation", "line"}:
        return InfrastructureCategory.POWER
    if str(properties.get("man_made") or "") in {
        "water_works",
        "water_tower",
        "pipeline",
    }:
        return InfrastructureCategory.WATER
    return None


def _intersects(asset: InfrastructureAsset, geometry: ExposureGeometry) -> bool:
    if asset.coordinate is not None:
        return contains_coordinate(geometry.geometry, asset.coordinate)
    if asset.geometry is not None:
        return geometries_intersect(geometry.geometry, asset.geometry)
    return path_intersects_geometry(asset.path, geometry.geometry)


def _timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("OSM source update time must include a timezone.")
    return parsed


def _bbox_area_km2(geometry: ExposureGeometry) -> float:
    west, south, east, north = geometry.geometry.bounds
    latitude_km = max(0.001, (north - south) * 111.195)
    longitude_km = max(
        0.001,
        (east - west) * 111.195 * cos(radians((south + north) / 2)),
    )
    return latitude_km * longitude_km


def _path_length_km(path: tuple[Coordinate, ...]) -> float:
    return sum(
        _distance_km(left, right) for left, right in zip(path, path[1:], strict=False)
    )


def _distance_km(left: Coordinate, right: Coordinate) -> float:
    latitude_delta = radians(right.latitude - left.latitude)
    longitude_delta = radians(right.longitude - left.longitude)
    value = (
        sin(latitude_delta / 2) ** 2
        + cos(radians(left.latitude))
        * cos(radians(right.latitude))
        * sin(longitude_delta / 2) ** 2
    )
    return 2 * 6_371.0088 * asin(sqrt(value))
