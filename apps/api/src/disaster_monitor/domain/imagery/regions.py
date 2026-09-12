"""Immutable, provenance-bearing WGS84 region values.

GeoJSON uses ``[longitude, latitude]`` while the domain uses named latitude and
longitude fields.  Keeping the conversion here makes axis order explicit at
every application boundary and prevents flattened perimeters from becoming a
substitute for polygon topology.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from math import cos, isfinite, radians
from typing import Any


class RegionRole(StrEnum):
    """Semantic role of a geometry in an imagery request."""

    SOURCE_FOOTPRINT = "source_footprint"
    CORE = "core"
    INSPECTION = "inspection"
    OBSERVED_USABLE_COVERAGE = "observed_usable_coverage"
    DISPLAY = "display"


class RegionSourceKind(StrEnum):
    """Kinds of source geography admitted by the region resolver."""

    MAPPED_IMPACT = "mapped_impact"
    OBSERVATION_MASK = "observation_mask"
    MODELED_HAZARD = "modeled_hazard"
    REPORTED_PLACE = "reported_place"
    VERIFIED_EVENT_POINT = "verified_event_point"
    USER_SELECTED = "user_selected"
    ACQUISITION_FOOTPRINT = "acquisition_footprint"


class AssociationStatus(StrEnum):
    """How source geography is associated with the selected incident."""

    CONFIRMED = "confirmed"
    POSSIBLE = "possible"
    UNKNOWN = "unknown"
    USER_SELECTED = "user_selected"
    UNRELATED = "unrelated"


def _aware(value: datetime | None) -> bool:
    return (
        value is not None and value.tzinfo is not None and value.utcoffset() is not None
    )


@dataclass(frozen=True, slots=True)
class Coordinate:
    """One finite WGS84 coordinate in named-axis order."""

    latitude: float
    longitude: float

    def __post_init__(self) -> None:
        if (
            not isfinite(self.latitude)
            or not isfinite(self.longitude)
            or not -90 <= self.latitude <= 90
            or not -180 <= self.longitude <= 180
        ):
            raise ValueError("Imagery coordinates must be finite WGS84 values.")

    def as_geojson(self) -> list[float]:
        """Return the coordinate in GeoJSON longitude/latitude order."""
        return [self.longitude, self.latitude]


@dataclass(frozen=True, slots=True)
class LinearRing:
    """A closed polygon ring retaining every source vertex."""

    coordinates: tuple[Coordinate, ...]

    def __post_init__(self) -> None:
        if len(self.coordinates) < 4:
            raise ValueError("A polygon ring requires at least four coordinates.")
        if self.coordinates[0] != self.coordinates[-1]:
            raise ValueError("A polygon ring must be closed.")
        if any(
            not isinstance(coordinate, Coordinate) for coordinate in self.coordinates
        ):
            raise TypeError("A polygon ring requires Coordinate values.")
        if any(
            first == second
            for first, second in zip(
                self.coordinates, self.coordinates[1:], strict=False
            )
        ):
            raise ValueError(
                "A polygon ring must not contain consecutive duplicate vertices."
            )

    def as_geojson(self) -> list[list[float]]:
        return [coordinate.as_geojson() for coordinate in self.coordinates]


@dataclass(frozen=True, slots=True)
class Polygon:
    """A polygon with an exterior ring and optional holes."""

    exterior: LinearRing
    holes: tuple[LinearRing, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.exterior, LinearRing) or any(
            not isinstance(hole, LinearRing) for hole in self.holes
        ):
            raise TypeError("Polygon boundaries must be LinearRing values.")
        if abs(_signed_ring_area(self.exterior)) < 1e-12:
            raise ValueError("A polygon exterior must contain a non-zero area.")

    def as_geojson(self) -> list[list[list[float]]]:
        return [self.exterior.as_geojson(), *(hole.as_geojson() for hole in self.holes)]


@dataclass(frozen=True, slots=True)
class MultiPolygon:
    """A topology-preserving collection of polygons."""

    polygons: tuple[Polygon, ...]

    def __post_init__(self) -> None:
        if not self.polygons:
            raise ValueError("A multipolygon requires at least one polygon.")
        if any(not isinstance(polygon, Polygon) for polygon in self.polygons):
            raise TypeError("A multipolygon requires Polygon values.")

    @property
    def positions(self) -> int:
        return sum(
            len(polygon.exterior.coordinates)
            + sum(len(hole.coordinates) for hole in polygon.holes)
            for polygon in self.polygons
        )

    @property
    def bounds(self) -> tuple[float, float, float, float]:
        coordinates = [
            coordinate
            for polygon in self.polygons
            for ring in (polygon.exterior, *polygon.holes)
            for coordinate in ring.coordinates
        ]
        return (
            min(item.longitude for item in coordinates),
            min(item.latitude for item in coordinates),
            max(item.longitude for item in coordinates),
            max(item.latitude for item in coordinates),
        )

    def as_geojson(self) -> dict[str, Any]:
        return {
            "type": "MultiPolygon",
            "coordinates": [polygon.as_geojson() for polygon in self.polygons],
        }

    def canonical_json(self) -> str:
        return json.dumps(self.as_geojson(), separators=(",", ":"), sort_keys=True)

    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class RegionSource:
    """Source identity and attribution retained with a geometry."""

    source_id: str
    source_kind: RegionSourceKind
    publisher: str
    reference: str
    source_crs: str = "EPSG:4326"
    captured_at: datetime | None = None
    represented_year: int | None = None
    attribution: str | None = None
    metadata: tuple[tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        if (
            not self.source_id.strip()
            or not self.publisher.strip()
            or not self.reference.strip()
        ):
            raise ValueError("A region source requires bounded identity and reference.")
        if not self.source_crs.strip():
            raise ValueError("A region source requires CRS metadata.")
        if self.captured_at is not None and not _aware(self.captured_at):
            raise ValueError("Region source timestamps must be timezone-aware.")
        if (
            self.represented_year is not None
            and not 1800 <= self.represented_year <= 2200
        ):
            raise ValueError("A represented boundary year is outside its bounds.")
        if any(not key.strip() or not value.strip() for key, value in self.metadata):
            raise ValueError(
                "Region source metadata keys and values must be non-empty."
            )


@dataclass(frozen=True, slots=True)
class RegionEvidence:
    """One candidate geographic evidence record supplied to resolution."""

    evidence_id: str
    geometry: MultiPolygon | None
    source: RegionSource
    association: AssociationStatus
    semantic_role: str
    component_id: str | None = None
    place_name: str | None = None
    country_code: str | None = None
    observed_at: datetime | None = None
    derivation_inputs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.evidence_id.strip() or not self.semantic_role.strip():
            raise ValueError("Region evidence requires stable identity and role.")
        if self.observed_at is not None and not _aware(self.observed_at):
            raise ValueError("Region evidence timestamps must be timezone-aware.")
        if self.country_code is not None:
            normalized = self.country_code.strip().upper()
            if len(normalized) != 3 or not normalized.isalpha():
                raise ValueError(
                    "Region evidence country codes must be ISO alpha-3 values."
                )
            object.__setattr__(self, "country_code", normalized)


@dataclass(frozen=True, slots=True)
class ImageryRegionVersion:
    """Immutable core/inspection scope for one imagery request version."""

    region_id: str
    version: int
    core: MultiPolygon
    inspection: MultiPolygon
    source_footprints: tuple[RegionEvidence, ...]
    core_role: RegionRole
    inspection_role: RegionRole = RegionRole.INSPECTION
    association: AssociationStatus = AssociationStatus.UNKNOWN
    parent_region_id: str | None = None
    derivation_inputs: tuple[str, ...] = ()
    display_geometry: MultiPolygon | None = None

    def __post_init__(self) -> None:
        if not self.region_id.strip() or self.version < 1:
            raise ValueError(
                "An imagery region requires a positive versioned identity."
            )
        if self.core_role is not RegionRole.CORE:
            raise ValueError("The core geometry must use the core region role.")
        if self.inspection_role is not RegionRole.INSPECTION:
            raise ValueError("The inspection geometry must use the inspection role.")
        if self.parent_region_id is not None and not self.parent_region_id.strip():
            raise ValueError("A parent region identity must not be empty.")

    @property
    def geometry_hash(self) -> str:
        payload = {
            "core": self.core.as_geojson(),
            "inspection": self.inspection.as_geojson(),
        }
        canonical = json.dumps(payload, separators=(",", ":"), sort_keys=True)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def polygon_from_geojson(value: Mapping[str, Any]) -> MultiPolygon:
    """Parse a Polygon/MultiPolygon GeoJSON object with explicit axis conversion."""
    geometry_type = value.get("type")
    coordinates = value.get("coordinates")
    if geometry_type not in {"Polygon", "MultiPolygon"} or not isinstance(
        coordinates, list
    ):
        raise ValueError(
            "Imagery geometry must be a Polygon or MultiPolygon GeoJSON object."
        )

    polygon_coordinates = [coordinates] if geometry_type == "Polygon" else coordinates
    polygons: list[Polygon] = []
    for raw_polygon in polygon_coordinates:
        if not isinstance(raw_polygon, list) or not raw_polygon:
            raise ValueError("A GeoJSON polygon must contain rings.")
        rings: list[LinearRing] = []
        for raw_ring in raw_polygon:
            if not isinstance(raw_ring, list):
                raise ValueError("A GeoJSON ring must be a coordinate list.")
            parsed: list[Coordinate] = []
            for raw_coordinate in raw_ring:
                if (
                    not isinstance(raw_coordinate, list)
                    or len(raw_coordinate) != 2
                    or any(
                        not isinstance(item, (int, float)) for item in raw_coordinate
                    )
                ):
                    raise ValueError(
                        "Imagery GeoJSON coordinates must be two numeric values."
                    )
                parsed.append(
                    Coordinate(float(raw_coordinate[1]), float(raw_coordinate[0]))
                )
            rings.append(LinearRing(tuple(parsed)))
        polygons.append(Polygon(rings[0], tuple(rings[1:])))
    return MultiPolygon(tuple(polygons))


def _signed_ring_area(ring: LinearRing) -> float:
    return (
        sum(
            first.longitude * second.latitude - second.longitude * first.latitude
            for first, second in zip(
                ring.coordinates, ring.coordinates[1:], strict=False
            )
        )
        / 2
    )


def approximate_area_km2(geometry: MultiPolygon) -> float:
    """Estimate geodesic area for policy limits without claiming survey accuracy.

    The computation uses a local equirectangular projection per polygon.  Exact
    provider-facing area/coverage work belongs to the infrastructure geometry
    adapter, while this deterministic fallback keeps domain validation usable
    without native geospatial libraries.
    """
    total = 0.0
    earth_radius_m = 6_371_008.8
    for polygon in geometry.polygons:
        reference_latitude = radians(
            sum(point.latitude for point in polygon.exterior.coordinates[:-1])
            / max(1, len(polygon.exterior.coordinates) - 1)
        )

        def ring_area(ring: LinearRing, latitude: float = reference_latitude) -> float:
            projected = [
                (
                    earth_radius_m * radians(point.longitude) * cos(latitude),
                    earth_radius_m * radians(point.latitude),
                )
                for point in ring.coordinates
            ]
            return abs(
                sum(
                    first[0] * second[1] - second[0] * first[1]
                    for first, second in zip(projected, projected[1:], strict=True)
                )
                / 2
            )

        total += ring_area(polygon.exterior) - sum(
            ring_area(hole) for hole in polygon.holes
        )
    return max(0.0, total / 1_000_000)


def point_geometry(coordinate: Coordinate) -> MultiPolygon:
    """Carry a point only through a metric buffer adapter.

    This helper intentionally does not turn a point into an impact polygon; it is
    useful for ports that need to carry a verified point separately from a region.
    """
    raise TypeError(
        "A point is not an imagery region; use the metric geometry port to buffer it."
    )
