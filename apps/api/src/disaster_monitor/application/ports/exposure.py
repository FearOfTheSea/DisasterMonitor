"""Consumer-owned seams for versioned exposure datasets."""

from typing import Protocol

from disaster_monitor.domain.exposure import (
    AccessRouteEstimate,
    ExposureGeometry,
    InfrastructureAsset,
    OsmCompletenessIndicator,
    PopulationExposureEstimate,
    RouteProfile,
)
from disaster_monitor.domain.imagery.regions import Coordinate


class PopulationExposureProvider(Protocol):
    async def estimate(
        self, geometry: ExposureGeometry
    ) -> PopulationExposureEstimate: ...


class AssetExposureProvider(Protocol):
    async def intersecting_assets(
        self, geometry: ExposureGeometry
    ) -> tuple[InfrastructureAsset, ...]: ...


class OsmCompletenessProvider(Protocol):
    async def completeness(
        self, geometry: ExposureGeometry
    ) -> OsmCompletenessIndicator: ...


class AccessRouteProvider(Protocol):
    async def route(
        self,
        origin: Coordinate,
        destination: Coordinate,
        profile: RouteProfile,
    ) -> AccessRouteEstimate: ...
