"""Coordinate population and asset intersections without impact inference."""

from collections.abc import Callable
from datetime import UTC, datetime

from disaster_monitor.application.ports.exposure import (
    AssetExposureProvider,
    OsmCompletenessProvider,
    PopulationExposureProvider,
)
from disaster_monitor.domain.exposure import (
    ExposureAnalysis,
    ExposureDatasetRole,
    ExposureGeometry,
    ExposureGeometryRole,
    PopulationDisagreement,
    PopulationExposureEstimate,
)

_DISPLAY_LABELS = {
    ExposureGeometryRole.MAPPED_HAZARD: (
        "Population/assets intersecting the mapped area"
    ),
    ExposureGeometryRole.FORECAST_HAZARD: (
        "Population/assets intersecting the forecast area"
    ),
    ExposureGeometryRole.MODELLED_HAZARD: (
        "Population/assets intersecting the modelled area"
    ),
}


class ExposureAnalysisService:
    def __init__(
        self,
        *,
        population_providers: tuple[PopulationExposureProvider, ...] = (),
        asset_provider: AssetExposureProvider | None = None,
        completeness_provider: OsmCompletenessProvider | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._population_providers = population_providers
        self._asset_provider = asset_provider
        self._completeness_provider = completeness_provider
        self._clock = clock

    async def execute(self, geometry: ExposureGeometry) -> ExposureAnalysis:
        estimates = tuple(
            [
                await provider.estimate(geometry)
                for provider in self._population_providers
            ]
        )
        geometry_hash = geometry.geometry.sha256()
        if any(item.geometry_hash != geometry_hash for item in estimates):
            raise ValueError("A provider estimate has mismatched geometry lineage.")
        ordered = tuple(
            sorted(
                estimates,
                key=lambda item: (
                    0 if item.dataset.role is ExposureDatasetRole.PRIMARY else 1,
                    item.dataset.dataset_id,
                ),
            )
        )
        assets = (
            await self._asset_provider.intersecting_assets(geometry)
            if self._asset_provider is not None
            else ()
        )
        completeness = (
            await self._completeness_provider.completeness(geometry)
            if self._completeness_provider is not None
            else None
        )
        return ExposureAnalysis(
            geometry=geometry,
            population_estimates=ordered,
            assets=tuple(
                sorted(assets, key=lambda item: (item.category.value, item.asset_id))
            ),
            population_disagreement=_disagreement(ordered),
            display_label=_DISPLAY_LABELS[geometry.role],
            calculated_at=self._clock(),
            limitations=(
                "Intersection is not evidence that a person or asset was affected.",
                "Population surfaces are modelled datasets with vintage, resolution, "
                "and allocation uncertainty.",
                "OpenStreetMap completeness varies; missing assets are not evidence "
                "of absence.",
            ),
            osm_completeness=completeness,
        )


def _disagreement(
    estimates: tuple[PopulationExposureEstimate, ...],
) -> PopulationDisagreement | None:
    primary = next(
        (
            item
            for item in estimates
            if item.dataset.role is ExposureDatasetRole.PRIMARY
        ),
        None,
    )
    secondary = next(
        (
            item
            for item in estimates
            if item.dataset.role is ExposureDatasetRole.SECONDARY
        ),
        None,
    )
    if primary is None or secondary is None:
        return None
    difference = abs(primary.population - secondary.population)
    return PopulationDisagreement(
        primary.dataset.dataset_id,
        secondary.dataset.dataset_id,
        difference,
        difference / primary.population if primary.population else None,
    )
