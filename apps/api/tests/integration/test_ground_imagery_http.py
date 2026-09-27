from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import httpx
import numpy as np
import pytest
from rasterio.io import MemoryFile
from rasterio.transform import from_bounds

from disaster_monitor.application.ground_imagery.models import GroundImageryRequestInput
from disaster_monitor.application.ground_imagery.request_limits import (
    GroundImageryRateLimitExceeded,
    GroundImageryRequestLimiter,
)
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
from disaster_monitor.application.ports.ground_imagery.jobs import preparation_job
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
from disaster_monitor.infrastructure.ground_imagery.memory_jobs import (
    InMemoryGroundImageryJobQueue,
)
from disaster_monitor.infrastructure.ground_imagery.memory_repository import (
    InMemoryGroundImageryRequestStore,
)
from disaster_monitor.infrastructure.ground_imagery.postgres_repository import (
    PostgresGroundImageryRequestStore,
)
from disaster_monitor.infrastructure.ground_imagery.raster_artifacts import (
    RasterioCogValidator,
    RasterioStoredArtifactTileRenderer,
)
from disaster_monitor.infrastructure.operations.postgres_repository import (
    PostgresOperationalRepository,
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


def _service(
    artifact_root: Path | None = None,
    *,
    job_queue: InMemoryGroundImageryJobQueue | None = None,
    rate_limiter: GroundImageryRequestLimiter | None = None,
    catalog: FakeCatalog | None = None,
    clock=None,
) -> GroundImageryService:
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
        catalog
        or FakeCatalog(
            (
                _observation(Sensor.SENTINEL_1, "s1-1"),
                _observation(Sensor.SENTINEL_2, "s2-1"),
            )
        ),
        InMemoryGroundImageryRequestStore(),
        clock=clock or (lambda: datetime(2024, 5, 20, tzinfo=UTC)),
        renderer=None if artifact_store is None else FakeRenderer(),
        raster_validator=None if artifact_store is None else RasterioCogValidator(),
        artifact_store=artifact_store,
        tile_renderer=(
            None
            if artifact_store is None
            else RasterioStoredArtifactTileRenderer(artifact_store)
        ),
        job_queue=job_queue,
        rate_limiter=rate_limiter,
    )


@pytest.mark.asyncio
async def test_refresh_and_reopen_discover_captures_after_the_original_search() -> None:
    first_search = datetime(2024, 5, 20, tzinfo=UTC)
    now = [first_search]
    original = _observation(Sensor.SENTINEL_2, "s2-original")
    later_capture = datetime(2024, 5, 22, tzinfo=UTC)
    newer = replace(
        _observation(Sensor.SENTINEL_2, "s2-new"),
        capture=CaptureInterval(later_capture, later_capture + timedelta(minutes=5)),
    )
    catalog = FakeCatalog((original,))
    service = _service(catalog=catalog, clock=lambda: now[0])
    request_input = GroundImageryRequestInput(
        incident_id="incident-1",
        reference_time=first_search,
        idempotency_key="ground-view:incident-1",
    )
    first = await service.create_request(request_input)

    now[0] = datetime(2024, 5, 23, tzinfo=UTC)
    catalog.observations = (original, newer)
    refreshed = await service.refresh(first.request_id)

    assert refreshed.request_version == 2
    assert refreshed.reference_time == now[0]
    assert refreshed.temporal_plan.reference_time == now[0]
    assert refreshed.region_resolution.region == first.region_resolution.region
    assert refreshed.selection is not None
    latest = refreshed.selection.for_sensor(Sensor.SENTINEL_2).for_role("latest_useful")
    assert latest.observation is not None
    assert latest.observation.identity.product_id == "s2-new"
    assert catalog.queries[-1].end == now[0]
    assert catalog.queries[-1].geometry == first.region_resolution.region.inspection

    reopened = await service.create_request(
        replace(request_input, reference_time=now[0])
    )
    assert reopened.request_id == first.request_id
    assert reopened.request_version == refreshed.request_version


@pytest.mark.asyncio
async def test_reopening_stale_ground_view_refreshes_only_with_explicit_flag() -> None:
    now = [datetime(2024, 5, 20, tzinfo=UTC)]
    catalog = FakeCatalog((_observation(Sensor.SENTINEL_2, "s2-original"),))
    service = _service(catalog=catalog, clock=lambda: now[0])
    input_value = GroundImageryRequestInput(
        incident_id="incident-1",
        reference_time=now[0],
        idempotency_key="stable-request",
    )
    first = await service.create_request(input_value)
    now[0] += timedelta(hours=2)

    unchanged = await service.create_request(
        replace(input_value, reference_time=now[0])
    )
    assert unchanged.request_version == 1

    updated = await service.create_request(
        replace(input_value, reference_time=now[0], refresh_if_stale=True)
    )
    assert updated.request_id == first.request_id
    assert updated.request_version == 2
    assert updated.reference_time == now[0]


@pytest.mark.asyncio
async def test_selecting_a_region_searches_through_the_current_time() -> None:
    now = [datetime(2024, 5, 20, tzinfo=UTC)]
    catalog = FakeCatalog((_observation(Sensor.SENTINEL_2, "s2-original"),))
    service = _service(catalog=catalog, clock=lambda: now[0])
    first = await service.create_request(
        GroundImageryRequestInput(incident_id="incident-1", reference_time=now[0])
    )
    await service.set_watch(first.request_id, enabled=True)
    now[0] += timedelta(days=2)

    replaced = await service.replace_region(first.request_id, GEOMETRY)

    assert replaced.request_version == 2
    assert replaced.reference_time == now[0]
    assert catalog.queries[-1].end == now[0]
    assert replaced.watch_enabled is True


@pytest.mark.asyncio
async def test_due_watch_discovers_a_new_capture_and_moves_its_next_check() -> None:
    now = [datetime(2024, 5, 20, tzinfo=UTC)]
    catalog = FakeCatalog((_observation(Sensor.SENTINEL_2, "s2-original"),))
    service = _service(catalog=catalog, clock=lambda: now[0])
    first = await service.create_request(
        GroundImageryRequestInput(incident_id="incident-1", reference_time=now[0])
    )
    watched = await service.set_watch(first.request_id, enabled=True)
    assert watched.next_check_at == now[0] + timedelta(hours=1)
    assert await service.refresh_next_due_watch() is None

    now[0] += timedelta(hours=1)
    newer = replace(
        _observation(Sensor.SENTINEL_2, "s2-new"),
        capture=CaptureInterval(
            now[0] - timedelta(minutes=10), now[0] - timedelta(minutes=5)
        ),
    )
    catalog.observations = (*catalog.observations, newer)
    refreshed = await service.refresh_next_due_watch()

    assert refreshed is not None
    assert refreshed.request_version == 2
    assert refreshed.reference_time == now[0]
    assert refreshed.next_check_at == now[0] + timedelta(hours=1)
    assert refreshed.selection is not None
    latest = refreshed.selection.for_sensor(Sensor.SENTINEL_2).for_role("latest_useful")
    assert latest.observation is not None
    assert latest.observation.identity.product_id == "s2-new"


@pytest.mark.asyncio
@pytest.mark.postgres
async def test_postgres_watch_claim_is_durable_and_single_use(
    postgres_dsn: str,
) -> None:
    await PostgresOperationalRepository(postgres_dsn).migrate()
    store = PostgresGroundImageryRequestStore(postgres_dsn)
    request = await _service().create_request(
        GroundImageryRequestInput(
            incident_id="incident-1",
            reference_time=datetime(2024, 5, 20, tzinfo=UTC),
        )
    )
    now = datetime(2024, 5, 20, 1, tzinfo=UTC)
    request = replace(
        request,
        request_id=f"ground-imagery:{uuid4().hex}",
        watch_enabled=True,
        watch_interval_seconds=3_600,
        next_check_at=now,
    )
    await store.save_request(request)

    assert await store.claim_due_watch(now=now) == request.request_id
    assert await store.claim_due_watch(now=now) is None
    claimed = await store.get_request(request.request_id)
    assert claimed is not None
    assert claimed.watch_enabled is True
    assert claimed.next_check_at == now + timedelta(hours=1)


@pytest.mark.asyncio
async def test_ground_request_stays_queued_until_all_enqueued_artifacts_exist(
    tmp_path: Path,
) -> None:
    queue = InMemoryGroundImageryJobQueue()
    service = _service(tmp_path, job_queue=queue)
    request = await service.create_request(
        GroundImageryRequestInput(
            incident_id="incident-1",
            reference_time=datetime(2024, 5, 20, tzinfo=UTC),
        )
    )
    selected = [
        (sensor, outcome.role)
        for sensor in request.requested_sensors
        for outcome in request.selection.for_sensor(sensor).selections
        if outcome.observation is not None
    ]
    assert len(selected) >= 2
    jobs = [
        preparation_job(
            request_id=request.request_id,
            request_version=request.request_version,
            sensor=sensor,
            role=role,
            overview=True,
            output_kind=None,
            now=request.updated_at,
        )
        for sensor, role in selected[:2]
    ]
    for job in jobs:
        await queue.enqueue(job)

    first = await queue.claim("worker", now=request.updated_at)
    assert first is not None
    updated = await service.execute_preparation_job(first)

    assert updated.state.value == "queued"
    assert len(updated.artifacts) == 1


@pytest.mark.asyncio
async def test_preparing_existing_artifact_does_not_spend_another_limit_slot(
    tmp_path: Path,
) -> None:
    limiter = GroundImageryRequestLimiter(
        clock=lambda: datetime(2024, 5, 20, tzinfo=UTC)
    )
    service = _service(tmp_path, rate_limiter=limiter)
    request = await service.create_request(
        GroundImageryRequestInput(
            incident_id="incident-1",
            reference_time=datetime(2024, 5, 20, tzinfo=UTC),
        )
    )
    first = await service.prepare_selection(
        request.request_id,
        sensor=Sensor.SENTINEL_2,
        role="first_useful_after_onset",
    )
    repeated = await service.prepare_selection(
        request.request_id,
        sensor=Sensor.SENTINEL_2,
        role="first_useful_after_onset",
    )

    assert repeated.artifacts == first.artifacts
    for _ in range(3):
        await limiter.claim_preparation()
    with pytest.raises(GroundImageryRateLimitExceeded):
        await limiter.claim_preparation()


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
async def test_ground_imagery_http_reuses_request_without_refresh_quota() -> None:
    now = datetime(2024, 5, 20, tzinfo=UTC)
    service = _service(rate_limiter=GroundImageryRequestLimiter(clock=lambda: now))
    app = create_app(overrides=AppDependencyOverrides(ground_imagery_service=service))
    payload = {
        "incident_id": "incident-1",
        "reference_time": "2024-05-20T00:00:00Z",
        "idempotency_key": "same-view",
    }
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        created = await client.post("/api/v1/ground-imagery/requests", json=payload)
        duplicate = await client.post("/api/v1/ground-imagery/requests", json=payload)
        request_id = created.json()["request_id"]
        limited = await client.post(
            f"/api/v1/ground-imagery/requests/{request_id}/refresh"
        )
        now += timedelta(hours=1)
        refreshed = await client.post(
            f"/api/v1/ground-imagery/requests/{request_id}/refresh"
        )

    assert created.status_code == duplicate.status_code == 202
    assert duplicate.json()["request_id"] == request_id
    assert limited.status_code == 429
    assert limited.headers["retry-after"] == "3600"
    assert refreshed.status_code == 202


@pytest.mark.asyncio
async def test_ground_imagery_http_publishes_validated_artifacts(
    tmp_path: Path,
) -> None:
    catalog = FakeCatalog(
        (
            _observation(Sensor.SENTINEL_1, "s1-1"),
            _observation(Sensor.SENTINEL_2, "s2-1"),
        )
    )
    service = _service(tmp_path, catalog=catalog)
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
        preview = await client.get(
            f"/api/v1/ground-imagery/artifacts/{artifact_id}/preview.png"
        )
        selection_manifest = await client.get(
            f"/api/v1/ground-imagery/selections/{selected['selection_id']}/manifest"
        )
        stac = await client.get(
            f"/api/v1/ground-imagery/requests/{body['request_id']}/stac"
        )
        readiness = await client.get("/api/v1/ground-imagery/readiness")
        catalog.observations = (
            replace(
                _observation(Sensor.SENTINEL_1, "s1-new"),
                capture=CaptureInterval(
                    datetime(2024, 5, 19, tzinfo=UTC),
                    datetime(2024, 5, 19, 0, 5, tzinfo=UTC),
                ),
            ),
            _observation(Sensor.SENTINEL_2, "s2-1"),
        )
        refreshed = await client.post(
            f"/api/v1/ground-imagery/requests/{body['request_id']}/refresh"
        )
        historical_manifest = await client.get(
            f"/api/v1/ground-imagery/selections/{selected['selection_id']}/manifest"
        )

    assert created.status_code == 202
    assert prepared.status_code == 202
    assert download.status_code == 200
    assert download.headers["etag"]
    assert download.headers["content-type"] == "image/tiff"
    assert tile.status_code == 200
    assert tile.content.startswith(b"\x89PNG\r\n\x1a\n")
    assert preview.status_code == 200
    assert preview.content.startswith(b"\x89PNG\r\n\x1a\n")
    assert selection_manifest.status_code == 200
    assert stac.status_code == 200
    assert stac.json()["items"][0]["assets"]["data"]["href"].endswith(
        f"/{artifact_id}/download"
    )
    assert readiness.json()["state"] == "ready"
    assert any(
        item["observation"]["product_id"] == "s1-1"
        for item in prepared.json()["artifacts"]
    ), (
        selected["observation"]["product_id"],
        [
            (item["sensor"], item["observation"]["product_id"])
            for item in prepared.json()["artifacts"]
        ],
    )
    assert refreshed.status_code == 202
    assert any(
        item["observation"]["product_id"] == "s1-1"
        for item in refreshed.json()["artifacts"]
    )
    assert historical_manifest.status_code == 200
    assert any(
        item["observation"]["product_id"] == "s1-1"
        for item in historical_manifest.json()["artifacts"]
    )
