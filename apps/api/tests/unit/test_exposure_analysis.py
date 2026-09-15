from datetime import UTC, datetime

import pytest

from disaster_monitor.application.exposure.analysis import ExposureAnalysisService
from disaster_monitor.application.ports.exposure import (
    AssetExposureProvider,
    PopulationExposureProvider,
)
from disaster_monitor.domain.exposure import (
    ExposureDataset,
    ExposureDatasetRole,
    ExposureGeometry,
    ExposureGeometryRole,
    InfrastructureAsset,
    InfrastructureCategory,
    PopulationExposureEstimate,
)
from disaster_monitor.domain.imagery.regions import Coordinate, polygon_from_geojson

NOW = datetime(2026, 9, 14, tzinfo=UTC)
GEOMETRY = polygon_from_geojson(
    {
        "type": "Polygon",
        "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 0]]],
    }
)


class FakePopulationProvider(PopulationExposureProvider):
    def __init__(self, estimate: PopulationExposureEstimate) -> None:
        self.estimate_result = estimate

    async def estimate(self, geometry: ExposureGeometry) -> PopulationExposureEstimate:
        return self.estimate_result


class FakeAssetProvider(AssetExposureProvider):
    async def intersecting_assets(
        self, geometry: ExposureGeometry
    ) -> tuple[InfrastructureAsset, ...]:
        return (
            InfrastructureAsset(
                asset_id="osm:hospital:1",
                name="Source hospital",
                category=InfrastructureCategory.HOSPITAL,
                coordinate=Coordinate(0.2, 0.2),
                source_dataset_id="osm-local",
                source_version="geofabrik-2026-09-01",
            ),
        )


def _dataset(
    dataset_id: str, role: ExposureDatasetRole, *, value: float
) -> PopulationExposureEstimate:
    dataset = ExposureDataset(
        dataset_id=dataset_id,
        publisher="Fixture population project",
        version="2026.1",
        vintage=2025,
        resolution_m=1000,
        license_name="Open data",
        source_url=f"https://data.example/{dataset_id}",
        role=role,
        uncertainty="Modelled gridded population with source uncertainty.",
    )
    return PopulationExposureEstimate(
        estimate_id=f"estimate:{dataset_id}",
        population=value,
        dataset=dataset,
        geometry_hash=GEOMETRY.sha256(),
        calculated_at=NOW,
        lineage=(dataset_id, GEOMETRY.sha256()),
    )


@pytest.mark.asyncio
async def test_exposure_keeps_intersection_semantics_and_dataset_disagreement() -> None:
    geometry = ExposureGeometry(
        geometry=GEOMETRY,
        role=ExposureGeometryRole.MAPPED_HAZARD,
        source_id="shakemap",
        source_version="us7000fixture:4",
        observed_at=NOW,
    )
    service = ExposureAnalysisService(
        population_providers=(
            FakePopulationProvider(
                _dataset("worldpop", ExposureDatasetRole.PRIMARY, value=1000)
            ),
            FakePopulationProvider(
                _dataset("ghsl", ExposureDatasetRole.SECONDARY, value=1250)
            ),
        ),
        asset_provider=FakeAssetProvider(),
        clock=lambda: NOW,
    )

    result = await service.execute(geometry)

    assert [item.dataset.dataset_id for item in result.population_estimates] == [
        "worldpop",
        "ghsl",
    ]
    assert result.population_disagreement is not None
    assert result.population_disagreement.relative_difference == pytest.approx(0.25)
    assert result.assets[0].category is InfrastructureCategory.HOSPITAL
    assert result.display_label == "Population/assets intersecting the mapped area"
    assert "affected" not in result.display_label.casefold()


@pytest.mark.asyncio
async def test_exposure_rejects_provider_estimate_for_different_geometry() -> None:
    geometry = ExposureGeometry(
        geometry=GEOMETRY,
        role=ExposureGeometryRole.MODELLED_HAZARD,
        source_id="ground-failure",
        source_version="v1",
        observed_at=NOW,
    )
    invalid = _dataset("worldpop", ExposureDatasetRole.PRIMARY, value=1000)
    invalid = PopulationExposureEstimate(
        estimate_id=invalid.estimate_id,
        population=invalid.population,
        dataset=invalid.dataset,
        geometry_hash="different",
        calculated_at=invalid.calculated_at,
        lineage=invalid.lineage,
    )

    with pytest.raises(ValueError, match="geometry lineage"):
        await ExposureAnalysisService(
            population_providers=(FakePopulationProvider(invalid),),
            clock=lambda: NOW,
        ).execute(geometry)
