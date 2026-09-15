"""Bounded route estimates and critical-facility proximity findings."""

from __future__ import annotations

from datetime import datetime
from hashlib import sha256
from math import asin, cos, radians, sin, sqrt

from disaster_monitor.application.ports.exposure import AccessRouteProvider
from disaster_monitor.domain.exposure import (
    AccessRouteEstimate,
    CriticalFacilityFinding,
    ExposureGeometry,
    InfrastructureAsset,
    RouteProfile,
)
from disaster_monitor.domain.imagery.regions import Coordinate, contains_coordinate


class RouteAccessContextService:
    def __init__(self, provider: AccessRouteProvider) -> None:
        self._provider = provider

    async def estimate(
        self,
        origin: Coordinate,
        destination: Coordinate,
        profile: RouteProfile,
    ) -> AccessRouteEstimate:
        result = await self._provider.route(origin, destination, profile)
        if result.origin != origin or result.destination != destination:
            raise ValueError("Route provider returned different endpoints.")
        return result


class CriticalFacilityProximityService:
    def __init__(self, *, maximum_distance_km: float = 10) -> None:
        if maximum_distance_km <= 0 or maximum_distance_km > 100:
            raise ValueError("Facility proximity distance is outside its bounds.")
        self._maximum_distance_km = maximum_distance_km

    def find(
        self,
        geometry: ExposureGeometry,
        assets: tuple[InfrastructureAsset, ...],
        *,
        dataset_updated_at: datetime,
        calculated_at: datetime,
    ) -> tuple[CriticalFacilityFinding, ...]:
        findings: list[CriticalFacilityFinding] = []
        for asset in assets:
            distance = _distance_to_geometry(asset, geometry)
            if distance is None or distance > self._maximum_distance_km:
                continue
            relationship = "intersects" if distance == 0 else "nearby"
            identity = sha256(
                f"{geometry.geometry.sha256()}|{asset.asset_id}|{relationship}".encode()
            ).hexdigest()[:24]
            findings.append(
                CriticalFacilityFinding(
                    finding_id=f"facility-proximity:{identity}",
                    asset_id=asset.asset_id,
                    asset_name=asset.name,
                    category=asset.category,
                    relationship=relationship,
                    distance_km=round(distance, 3),
                    hazard_geometry_source_id=geometry.source_id,
                    hazard_geometry_source_version=geometry.source_version,
                    asset_dataset_id=asset.source_dataset_id,
                    asset_dataset_version=asset.source_version,
                    dataset_updated_at=dataset_updated_at,
                    calculated_at=calculated_at,
                    limitation=(
                        "OpenStreetMap facility coverage and source age vary; "
                        "proximity "
                        "does not establish damage, access, operation, or need."
                    ),
                )
            )
        return tuple(
            sorted(findings, key=lambda item: (item.distance_km, item.asset_id))
        )


def _distance_to_geometry(
    asset: InfrastructureAsset, geometry: ExposureGeometry
) -> float | None:
    candidates: tuple[Coordinate, ...]
    if asset.coordinate is not None:
        if contains_coordinate(geometry.geometry, asset.coordinate):
            return 0
        candidates = (asset.coordinate,)
    elif asset.path:
        if any(contains_coordinate(geometry.geometry, point) for point in asset.path):
            return 0
        candidates = asset.path
    elif asset.geometry is not None:
        candidates = tuple(
            point
            for polygon in asset.geometry.polygons
            for point in polygon.exterior.coordinates
        )
        if any(contains_coordinate(geometry.geometry, point) for point in candidates):
            return 0
    else:
        return None
    boundary = tuple(
        point
        for polygon in geometry.geometry.polygons
        for point in polygon.exterior.coordinates
    )
    return min(_distance_km(left, right) for left in candidates for right in boundary)


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
