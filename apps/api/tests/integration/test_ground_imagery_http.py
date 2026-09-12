from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import numpy as np
import pytest
from rasterio.io import MemoryFile
from rasterio.transform import from_bounds

from disaster_monitor.application.ground_imagery.resolve_region import (
    GroundImageryRegionResolver,
)
from disaster_monitor.application.ground_imagery.service import GroundImageryService
from disaster_monitor.application.ground_imagery.temporal_policy import ImpactOnset
from disaster_monitor.application.ports.ground_imagery.catalog import (
    GroundImageryCatalogPage,
    GroundImageryCatalogQuery,
)
from disaster_monitor.application.ports.ground_imagery.incidents import (
    IncidentImageryContext,
)
from disaster_monitor.application.ports.ground_imagery.rendering import (
    RenderedRaster,
    RenderRequest,
)
from disaster_monitor.domain.disaster import Disaster
from disaster_monitor.domain.imagery.observations import (
    AcquisitionIdentity,
    CaptureInterval,
    Observation,
    ObservationQuality,
    ObservationReadiness,
    QualityState,
    Sensor,
)
from disaster_monitor.domain.imagery.regions import (
    AssociationStatus,
    RegionEvidence,
    RegionSource,
    RegionSourceKind,
    polygon_from_geojson,
)
from disaster_monitor.infrastructure.composition import AppDependencyOverrides
from disaster_monitor.infrastructure.ground_imagery.artifact_store import (
    FilesystemImageryArtifactStore,
)
from disaster_monitor.infrastructure.ground_imagery.geometry import (
    GeodesicGeometryEngine,
)
from disaster_monitor.infrastructure.ground_imagery.memory_repository import (
    InMemoryGroundImageryRequestStore,
)
from disaster_monitor.infrastructure.ground_imagery.raster_artifacts import (
    RasterioCogValidator,
    RasterioStoredArtifactTileRenderer,
)
from disaster_monitor.main import create_app

GEOMETRY = polygon_from_geojson(
    {
        "type": "Polygon",
        "coordinates": [[[10, 1], [11, 1], [11, 2], [10, 2], [10, 1]]],
    }
)


@dataclass
class FakeIncidentReader:
    context: IncidentImageryContext

    async def get_imagery_context(self, incident_id: str):
        return self.context if incident_id == self.context.incident_id else None


class FakeCatalog:
    def __init__(self, observations: tuple[Observation, ...]):
        self.observations = observations
        self.queries: list[GroundImageryCatalogQuery] = []

    async def search(
        self, query: GroundImageryCatalogQuery
    ) -> GroundImageryCatalogPage:
        self.queries.append(query)
        return GroundImageryCatalogPage(
            self.observations, None, len(self.observations), True
        )

    async def aclose(self) -> None:
        return None


class FakeRenderer:
    async def render(self, request: RenderRequest) -> RenderedRaster:
        grid = request.grid
        with MemoryFile() as memory:
            with memory.open(
                driver="GTiff",
                width=grid.width,
                height=grid.height,
                count=3,
                dtype="uint8",
                crs=grid.crs,
                transform=from_bounds(
                    grid.min_x,
                    grid.min_y,
                    grid.max_x,
                    grid.max_y,
                    grid.width,
                    grid.height,
                ),
            ) as dataset:
                dataset.write(np.full((3, grid.height, grid.width), 100, dtype="uint8"))
            content = memory.read()
        return RenderedRaster(
            content=content,
            media_type="image/tiff",
            source_product_ids=(request.observation.identity.product_id,),
        )

    async def aclose(self) -> None:
        return None


def _observation(sensor: Sensor, product_id: str) -> Observation:
    timestamp = datetime(2024, 5, 12, tzinfo=UTC)
    return Observation(
        observation_id=product_id,
        sensor=sensor,
        identity=AcquisitionIdentity(
            product_id=product_id,
            provider="fixture",
            acquisition_id=product_id,
        ),
        capture=CaptureInterval(timestamp, timestamp + timedelta(minutes=5)),
        footprint=GEOMETRY,
        readiness=ObservationReadiness.RENDERABLE,
        quality=ObservationQuality(
            covered_fraction=1,
            usable_fraction=0.9,
            obscured_fraction=0.1,
            uncertain_fraction=0,
            uncovered_fraction=0,
            component_usable_fractions=(("core", 0.9),),
            quality_state=QualityState.USEFUL,
            mask_definition="fixture-v1",
        ),
        mode="IW" if sensor is Sensor.SENTINEL_1 else None,
        relative_orbit=24 if sensor is Sensor.SENTINEL_1 else None,
        orbit_direction="descending" if sensor is Sensor.SENTINEL_1 else None,
        polarizations=("VV", "VH") if sensor is Sensor.SENTINEL_1 else (),
        recipe_version="gamma0-terrain-v1" if sensor is Sensor.SENTINEL_1 else None,
    )


def _service(artifact_root: Path | None = None) -> GroundImageryService:
    source = RegionSource(
        source_id="fixture:impact",
        source_kind=RegionSourceKind.MAPPED_IMPACT,
        publisher="Fixture",
        reference="https://example.test/impact",
    )
    context = IncidentImageryContext(
        incident_id="incident-1",
        disaster=Disaster.FLOOD,
        country_code="BRA",
        event_time=datetime(2024, 5, 5, tzinfo=UTC),
        onset=ImpactOnset.exact(
            datetime(2024, 5, 5, tzinfo=UTC), source_id="fixture:event"
        ),
        evidence=(
            RegionEvidence(
                evidence_id="impact",
                geometry=GEOMETRY,
                source=source,
                association=AssociationStatus.CONFIRMED,
                semantic_role="mapped impact",
            ),
        ),
    )
    artifact_store = (
        None if artifact_root is None else FilesystemImageryArtifactStore(artifact_root)
    )
    return GroundImageryService(
        FakeIncidentReader(context),
        GroundImageryRegionResolver(GeodesicGeometryEngine()),
        FakeCatalog(
            (
                _observation(Sensor.SENTINEL_1, "s1-1"),
                _observation(Sensor.SENTINEL_2, "s2-1"),
            )
        ),
        InMemoryGroundImageryRequestStore(),
        clock=lambda: datetime(2024, 5, 20, tzinfo=UTC),
        renderer=None if artifact_store is None else FakeRenderer(),
        raster_validator=None if artifact_store is None else RasterioCogValidator(),
        artifact_store=artifact_store,
        tile_renderer=(
            None
            if artifact_store is None
            else RasterioStoredArtifactTileRenderer(artifact_store)
        ),
    )


@pytest.mark.asyncio
async def test_ground_imagery_http_exposes_region_time_sensor_states_and_manifest() -> (
    None
):
    service = _service()
    app = create_app(overrides=AppDependencyOverrides(ground_imagery_service=service))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/api/v1/ground-imagery/requests",
            headers={"Content-Type": "application/json"},
            json={
                "incident_id": "incident-1",
                "reference_time": "2024-05-20T00:00:00Z",
                "idempotency_key": "request-1",
            },
        )
        request_id = response.json()["request_id"]
        status_response = await client.get(
            f"/api/v1/ground-imagery/requests/{request_id}"
        )
        manifest = await client.get(
            f"/api/v1/ground-imagery/requests/{request_id}/manifest"
        )
        duplicate = await client.post(
            "/api/v1/ground-imagery/requests",
            json={
                "incident_id": "incident-1",
                "reference_time": "2024-05-20T00:00:00Z",
                "idempotency_key": "request-1",
            },
        )
        refreshed = await client.post(
            f"/api/v1/ground-imagery/requests/{request_id}/refresh"
        )

    assert response.status_code == 202
    assert status_response.status_code == 200
    assert duplicate.status_code == 202
    assert duplicate.json()["request_id"] == request_id
    assert refreshed.status_code == 202
    body = status_response.json()
    refreshed_body = refreshed.json()
    assert body["region"]["state"] == "resolved"
    assert refreshed_body["request_version"] == body["request_version"] + 1
    assert (
        refreshed_body["region"]["region"]["region_id"]
        == body["region"]["region"]["region_id"]
    )
    assert (
        refreshed_body["region"]["region"]["association"]
        == body["region"]["region"]["association"]
    )
    assert {item["sensor"] for item in body["sensors"]} == {
        "sentinel-1",
        "sentinel-2",
    }
    assert manifest.status_code == 200
    assert manifest.json()["temporal_policy_version"] == "sentinel-ground-view-v1"


@pytest.mark.asyncio
async def test_ground_imagery_http_preserves_needs_region_without_catalog_search() -> (
    None
):
    service = _service()
    reader = service._context_reader  # noqa: SLF001 - test fixture replacement
    reader.context = IncidentImageryContext(
        incident_id="needs-region",
        disaster=Disaster.FLOOD,
        country_code="BRA",
        event_time=datetime(2024, 5, 5, tzinfo=UTC),
    )
    app = create_app(overrides=AppDependencyOverrides(ground_imagery_service=service))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/api/v1/ground-imagery/requests",
            json={"incident_id": "needs-region"},
        )

    assert response.status_code == 202
    assert response.json()["state"] == "needs_region"


@pytest.mark.asyncio
async def test_ground_imagery_http_publishes_validated_artifacts(
    tmp_path: Path,
) -> None:
    service = _service(tmp_path)
    app = create_app(overrides=AppDependencyOverrides(ground_imagery_service=service))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        created = await client.post(
            "/api/v1/ground-imagery/requests",
            json={
                "incident_id": "incident-1",
                "reference_time": "2024-05-20T00:00:00Z",
            },
        )
        body = created.json()
        selected = next(
            item
            for sensor in body["sensors"]
            if sensor["sensor"] == "sentinel-1"
            for item in sensor["selections"]
            if item["role"] == "latest_useful" and item["observation"] is not None
        )
        prepared = await client.post(
            f"/api/v1/ground-imagery/requests/{body['request_id']}/prepare",
            json={
                "sensor": "sentinel-1",
                "role": "latest_useful",
            },
        )
        artifact_id = prepared.json()["artifacts"][0]["artifact_id"]
        download = await client.get(
            f"/api/v1/ground-imagery/artifacts/{artifact_id}/download"
        )
        tile = await client.get(
            f"/api/v1/ground-imagery/artifacts/{artifact_id}/tiles/0/0/0.png"
        )
        selection_manifest = await client.get(
            f"/api/v1/ground-imagery/selections/{selected['selection_id']}/manifest"
        )
        readiness = await client.get("/api/v1/ground-imagery/readiness")

    assert created.status_code == 202
    assert prepared.status_code == 202
    assert download.status_code == 200
    assert download.headers["etag"]
    assert download.headers["content-type"] == "image/tiff"
    assert tile.status_code == 200
    assert tile.content.startswith(b"\x89PNG\r\n\x1a\n")
    assert selection_manifest.status_code == 200
    assert readiness.json()["state"] == "ready"
