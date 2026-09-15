"""Consumer-owned seams for versioned exposure datasets."""

from typing import Protocol

from disaster_monitor.domain.exposure import (
    ExposureGeometry,
    InfrastructureAsset,
    PopulationExposureEstimate,
)


class PopulationExposureProvider(Protocol):
    async def estimate(
        self, geometry: ExposureGeometry
    ) -> PopulationExposureEstimate: ...


class AssetExposureProvider(Protocol):
    async def intersecting_assets(
        self, geometry: ExposureGeometry
    ) -> tuple[InfrastructureAsset, ...]: ...
