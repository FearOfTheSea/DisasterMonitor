from datetime import UTC, datetime, timedelta

import pytest

from disaster_monitor.application.exposure.access_context import (
    CriticalFacilityProximityService,
    RouteAccessContextService,
)
from disaster_monitor.application.exposure.analysis import ExposureAnalysisService
from disaster_monitor.domain.exposure import (
    AccessRouteEstimate,
    ExposureGeometry,
    ExposureGeometryRole,
    InfrastructureAsset,
    InfrastructureCategory,
    OsmCompletenessIndicator,
    RouteProfile,
)
from disaster_monitor.domain.imagery.regions import Coordinate, polygon_from_geojson

NOW = datetime(2026, 9, 16, 8, tzinfo=UTC)
GEOMETRY = ExposureGeometry(
    geometry=polygon_from_geojson(
        {
            "type": "Polygon",
            "coordinates": [[[106, 21], [107, 21], [107, 22], [106, 21]]],
        }
    ),
    role=ExposureGeometryRole.MAPPED_HAZARD,
    source_id="source-hazard-footprint",
    source_version="v2",
    observed_at=NOW - timedelta(hours=1),
)


class FakeCompletenessProvider:
    async def completeness(
        self, geometry: ExposureGeometry
    ) -> OsmCompletenessIndicator:
        return OsmCompletenessIndicator(
            dataset_id="osm-local",
            dataset_version="geofabrik-2026-09-01",
            source_updated_at=NOW - timedelta(days=15),
            calculated_at=NOW,
            mapped_feature_count=25,
            named_feature_fraction=0.6,
            road_density_km_per_sq_km=0.25,
            critical_facility_density_per_sq_km=0.02,
            quality="limited",
            limitation=(
                "Mapping density and source age are proxies, not completeness proof."
            ),
        )


class FakeRouteProvider:
    async def route(
        self,
        origin: Coordinate,
        destination: Coordinate,
        profile: RouteProfile,
    ) -> AccessRouteEstimate:
        return AccessRouteEstimate(
            route_id="route:one",
            origin=origin,
            destination=destination,
            profile=profile,
            path=(origin, destination),
            distance_m=1500,
            duration_seconds=300,
            provider="self-hosted-osrm",
            data_version="osm-2026-09-01",
            calculated_at=NOW,
            limitation=(
                "Estimated access visualization only; not an evacuation route or "
                "safety guarantee."
            ),
        )


@pytest.mark.asyncio
async def test_exposure_reports_osm_completeness_instead_of_implying_absence() -> None:
    result = await ExposureAnalysisService(
        completeness_provider=FakeCompletenessProvider(), clock=lambda: NOW
    ).execute(GEOMETRY)

    assert result.osm_completeness is not None
    assert result.osm_completeness.quality == "limited"
    assert any("missing assets are not evidence" in item for item in result.limitations)


@pytest.mark.asyncio
async def test_route_context_is_bounded_and_never_described_as_safe() -> None:
    result = await RouteAccessContextService(FakeRouteProvider()).estimate(
        Coordinate(21.1, 106.1),
        Coordinate(21.2, 106.2),
        RouteProfile.DRIVING,
    )

    assert result.provider == "self-hosted-osrm"
    assert "not an evacuation route" in result.limitation
    assert "safe route" not in result.limitation.casefold()


def test_critical_facility_findings_use_source_geometry_and_data_age_caveats() -> None:
    hospital = InfrastructureAsset(
        asset_id="osm:hospital:1",
        name="Test Hospital",
        category=InfrastructureCategory.HOSPITAL,
        source_dataset_id="openstreetmap-local",
        source_version="geofabrik-2026-09-01",
        coordinate=Coordinate(21.2, 106.2),
    )
    far_school = InfrastructureAsset(
        asset_id="osm:school:2",
        name="Far School",
        category=InfrastructureCategory.SCHOOL,
        source_dataset_id="openstreetmap-local",
        source_version="geofabrik-2026-09-01",
        coordinate=Coordinate(30, 120),
    )
    findings = CriticalFacilityProximityService(maximum_distance_km=20).find(
        GEOMETRY,
        (hospital, far_school),
        dataset_updated_at=NOW - timedelta(days=15),
        calculated_at=NOW,
    )

    assert len(findings) == 1
    assert findings[0].asset_id == hospital.asset_id
    assert findings[0].relationship == "intersects"
    assert findings[0].hazard_geometry_source_id == GEOMETRY.source_id
    assert "OpenStreetMap" in findings[0].limitation
