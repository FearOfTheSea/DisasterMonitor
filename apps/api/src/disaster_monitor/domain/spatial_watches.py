"""Local spatial watch definitions and deterministic intersection findings."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from math import asin, cos, isfinite, pi, radians, sin, sqrt

from disaster_monitor.domain.disaster_types import _is_aware
from disaster_monitor.domain.imagery.regions import (
    Coordinate,
    LinearRing,
    MultiPolygon,
    Polygon,
)


class SpatialInputKind(StrEnum):
    POLYGON = "polygon"
    CIRCLE = "circle"
    BOUNDING_BOX = "bounding_box"


class LocalAssetKind(StrEnum):
    HOME = "home"
    OFFICE = "office"
    WAREHOUSE = "warehouse"
    HOSPITAL = "hospital"
    ROUTE_CORRIDOR = "route_corridor"
    OTHER = "other"


class WatchGeometryRole(StrEnum):
    OBSERVED_HAZARD = "observed_hazard"
    FORECAST_HAZARD = "forecast_hazard"
    MODELLED_HAZARD = "modelled_hazard"
    OFFICIAL_WARNING = "official_warning"


@dataclass(frozen=True, slots=True)
class AreaOfInterestScope:
    scope_id: str
    name: str
    input_kind: SpatialInputKind
    geometry: MultiPolygon
    version: str
    updated_at: datetime

    def __post_init__(self) -> None:
        if any(not value.strip() for value in (self.scope_id, self.name, self.version)):
            raise ValueError("Area-of-interest scopes require identity and version.")
        if not _is_aware(self.updated_at):
            raise ValueError("Area-of-interest update time must be timezone-aware.")

    @classmethod
    def polygon(
        cls,
        *,
        scope_id: str,
        name: str,
        geometry: MultiPolygon,
        version: str,
        updated_at: datetime,
    ) -> AreaOfInterestScope:
        return cls(
            scope_id, name, SpatialInputKind.POLYGON, geometry, version, updated_at
        )

    @classmethod
    def bounding_box(
        cls,
        *,
        scope_id: str,
        name: str,
        min_latitude: float,
        min_longitude: float,
        max_latitude: float,
        max_longitude: float,
        version: str,
        updated_at: datetime,
    ) -> AreaOfInterestScope:
        if min_latitude >= max_latitude or min_longitude >= max_longitude:
            raise ValueError("Area-of-interest bounding box is invalid.")
        coordinates = (
            Coordinate(min_latitude, min_longitude),
            Coordinate(min_latitude, max_longitude),
            Coordinate(max_latitude, max_longitude),
            Coordinate(max_latitude, min_longitude),
            Coordinate(min_latitude, min_longitude),
        )
        return cls(
            scope_id,
            name,
            SpatialInputKind.BOUNDING_BOX,
            MultiPolygon((Polygon(LinearRing(coordinates)),)),
            version,
            updated_at,
        )

    @classmethod
    def circle(
        cls,
        *,
        scope_id: str,
        name: str,
        center: Coordinate,
        radius_km: float,
        version: str,
        updated_at: datetime,
    ) -> AreaOfInterestScope:
        if not isfinite(radius_km) or not 0 < radius_km <= 2_000:
            raise ValueError("Area-of-interest radius must be between 0 and 2000 km.")
        angular = radius_km / 6371.0088
        latitude = radians(center.latitude)
        longitude = radians(center.longitude)
        coordinates: list[Coordinate] = []
        for step in range(64):
            bearing = 2 * pi * step / 64
            target_latitude = asin(
                sin(latitude) * cos(angular)
                + cos(latitude) * sin(angular) * cos(bearing)
            )
            target_longitude = longitude + asin(
                sin(bearing) * sin(angular) / max(cos(target_latitude), 1e-12)
            )
            coordinates.append(
                Coordinate(
                    target_latitude * 180 / pi,
                    ((target_longitude * 180 / pi + 180) % 360) - 180,
                )
            )
        coordinates.append(coordinates[0])
        return cls(
            scope_id,
            name,
            SpatialInputKind.CIRCLE,
            MultiPolygon((Polygon(LinearRing(tuple(coordinates))),)),
            version,
            updated_at,
        )


@dataclass(frozen=True, slots=True)
class LocalAsset:
    asset_id: str
    name: str
    kind: LocalAssetKind
    version: str
    updated_at: datetime
    coordinate: Coordinate | None = None
    geometry: MultiPolygon | None = None
    route: tuple[Coordinate, ...] = ()

    def __post_init__(self) -> None:
        if any(not value.strip() for value in (self.asset_id, self.name, self.version)):
            raise ValueError("Local assets require identity and version.")
        if not _is_aware(self.updated_at):
            raise ValueError("Local asset update time must be timezone-aware.")
        count = sum(
            (self.coordinate is not None, self.geometry is not None, bool(self.route))
        )
        if count != 1 or (self.route and len(self.route) < 2):
            raise ValueError("A local asset requires exactly one valid geometry.")


@dataclass(frozen=True, slots=True)
class WatchGeometryEvidence:
    evidence_id: str
    geometry: MultiPolygon
    geometry_version: str
    role: WatchGeometryRole
    source_id: str
    observed_at: datetime

    def __post_init__(self) -> None:
        if any(
            not value.strip()
            for value in (self.evidence_id, self.geometry_version, self.source_id)
        ):
            raise ValueError("Watch evidence requires source identity and version.")
        if not _is_aware(self.observed_at):
            raise ValueError("Watch evidence time must be timezone-aware.")


@dataclass(frozen=True, slots=True)
class WatchTriggerPolicy:
    max_distance_km: float = 0

    def __post_init__(self) -> None:
        if not isfinite(self.max_distance_km) or not 0 <= self.max_distance_km <= 500:
            raise ValueError("Watch distance policy must be between 0 and 500 km.")


@dataclass(frozen=True, slots=True)
class WatchFinding:
    finding_id: str
    watch_id: str
    asset_id: str
    asset_name: str
    asset_version: str
    evidence_id: str
    source_id: str
    role: WatchGeometryRole
    geometry_version: str
    geometry_hash: str
    distance_km: float
    created_at: datetime
    summary: str

    def __post_init__(self) -> None:
        text = (
            self.finding_id,
            self.watch_id,
            self.asset_id,
            self.asset_name,
            self.asset_version,
            self.evidence_id,
            self.source_id,
            self.geometry_version,
            self.summary,
        )
        if any(not value.strip() for value in text) or len(self.geometry_hash) != 64:
            raise ValueError("Watch findings require complete deterministic lineage.")
        if not _is_aware(self.created_at):
            raise ValueError("Watch finding time must be timezone-aware.")


def coordinate_distance_km(first: Coordinate, second: Coordinate) -> float:
    latitude_delta = radians(second.latitude - first.latitude)
    longitude_delta = radians(second.longitude - first.longitude)
    first_latitude = radians(first.latitude)
    second_latitude = radians(second.latitude)
    value = sin(latitude_delta / 2) ** 2 + (
        cos(first_latitude) * cos(second_latitude) * sin(longitude_delta / 2) ** 2
    )
    return 6371.0088 * 2 * asin(min(1, sqrt(value)))
