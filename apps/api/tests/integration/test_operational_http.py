from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
from conftest import FakeLanguageModel

from disaster_monitor.application.ports.geography import (
    CountryCatalogUpdateState,
    CountryCatalogUpdateStatus,
    CountryCatalogUpdateTrigger,
)
from disaster_monitor.application.services.operational_ingestion import (
    AcquiredSourcePayload,
    SnapshotPersistenceService,
)
from disaster_monitor.domain.operations import WorldStateVersionRecord
from disaster_monitor.infrastructure.configuration import Settings
from disaster_monitor.infrastructure.operations.filesystem_blob_store import (
    FilesystemBlobStore,
)
from disaster_monitor.infrastructure.operations.memory_repository import (
    InMemoryOperationalRepository,
)
from disaster_monitor.main import create_app

NOW = datetime(2026, 8, 13, 8, tzinfo=UTC)


class FakeCountryCatalogAutomation:
    def __init__(self) -> None:
        self.requested: list[CountryCatalogUpdateTrigger] = []

    def status(self) -> CountryCatalogUpdateStatus:
        return CountryCatalogUpdateStatus(
            CountryCatalogUpdateState.UNCHANGED,
            "natural-earth-5.1.2.tzdb-2026b.test",
            242,
            True,
            last_attempt_at=NOW,
            last_success_at=NOW,
            next_scheduled_at=datetime(2026, 9, 1, tzinfo=UTC),
            message="Catalog is current.",
        )

    async def request_update(
        self, trigger: CountryCatalogUpdateTrigger
    ) -> CountryCatalogUpdateStatus:
        self.requested.append(trigger)
        current = self.status()
        return CountryCatalogUpdateStatus(
            CountryCatalogUpdateState.UPDATED,
            current.active_version,
            current.country_count,
            True,
            trigger=trigger,
            last_attempt_at=NOW,
            last_success_at=NOW,
            next_scheduled_at=current.next_scheduled_at,
            message="Catalog update completed.",
        )

    async def start(self) -> None:
        return None

    async def aclose(self) -> None:
        return None


@pytest.mark.asyncio
async def test_operational_status_history_and_attributed_review(tmp_path: Path) -> None:
    repository = InMemoryOperationalRepository()
    snapshot = await SnapshotPersistenceService(
        repository, FilesystemBlobStore(tmp_path / "blobs")
    ).persist(
        AcquiredSourcePayload(
            source_id="usgs-earthquakes",
            canonical_request_identity="request:usgs-earthquakes:test",
            provider_revision="catalog-1",
            content=b"bounded warning",
            content_type="application/geo+json",
            response_status=200,
            retrieved_at=NOW,
            published_at=NOW,
            observed_at=None,
            rights_id="usgs-terms-2026-08",
        )
    )
    world_state = WorldStateVersionRecord(
        "world-state:test",
        "physical-event:test",
        "sha256:" + "a" * 64,
        "sha256:" + "b" * 64,
        "evidence-world-state.v1",
        NOW,
    )
    await repository.append_world_state(world_state)
    app = create_app(
        settings=Settings(
            operational_blob_root=tmp_path / "api-blobs",
            trusted_operator_identity_enabled=True,
            trusted_operator_identity_header="x-custom-operator",
        ),
        model=FakeLanguageModel(),
        operational_repository=repository,
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        providers = await client.get("/api/v1/operations/providers")
        history = await client.get("/api/v1/operations/evidence-history")
        metrics = await client.get("/api/v1/metrics")
        missing_identity = await client.post(
            "/api/v1/operations/operator-actions",
            json={
                "state_version": world_state.state_version,
                "decision": "reviewed",
                "rationale": "Checked the source snapshot and freshness.",
            },
        )
        invalid_identity = await client.post(
            "/api/v1/operations/operator-actions",
            headers={"x-custom-operator": "o" * 201},
            json={
                "state_version": world_state.state_version,
                "decision": "reviewed",
                "rationale": "An overlong identity must not be accepted.",
            },
        )
        review = await client.post(
            "/api/v1/operations/operator-actions",
            headers={"x-custom-operator": "operator-7"},
            json={
                "state_version": world_state.state_version,
                "decision": "reviewed",
                "rationale": "Checked the source snapshot and freshness.",
                "evidence_ids": [snapshot.snapshot_id],
                "policy_ids": ["human-review-v1"],
            },
        )

    assert providers.status_code == 200
    assert len(providers.json()) == 2
    by_source = {item["source_id"]: item for item in providers.json()}
    assert by_source["usgs-earthquakes"]["last_success_at"] is not None
    assert history.status_code == 200
    assert history.json()[0]["snapshot_id"] == snapshot.snapshot_id
    assert "blob_uri" not in history.json()[0]
    assert history.json()[0]["content_available"] is True
    assert metrics.status_code == 200
    assert "disastermonitor_http_requests_total" in metrics.text
    assert 'disastermonitor_ingest_jobs{status="queued"} 0.0' in metrics.text
    assert missing_identity.status_code == 401
    assert invalid_identity.status_code == 401
    assert review.status_code == 201
    assert review.json()["operator_id"] == "operator-7"
    assert len(repository.operator_actions) == 1
    assert len(repository.audit_events) == 1


@pytest.mark.asyncio
async def test_operator_review_is_fail_closed_without_identity_boundary(
    tmp_path: Path,
) -> None:
    app = create_app(
        settings=Settings(operational_blob_root=tmp_path),
        model=FakeLanguageModel(),
        operational_repository=InMemoryOperationalRepository(),
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/api/v1/operations/operator-actions",
            headers={"x-disastermonitor-operator": "untrusted-browser-value"},
            json={
                "state_version": "world-state:missing",
                "decision": "approved_bounded",
                "rationale": "This must not be accepted without trusted identity.",
            },
        )

    assert response.status_code == 503


@pytest.mark.asyncio
async def test_country_catalog_status_and_manual_update(tmp_path: Path) -> None:
    automation = FakeCountryCatalogAutomation()
    app = create_app(
        settings=Settings(
            operational_blob_root=tmp_path,
            country_catalog_root=tmp_path / "geography",
        ),
        model=FakeLanguageModel(),
        operational_repository=InMemoryOperationalRepository(),
        country_catalog_automation=automation,
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        status_response = await client.get("/api/v1/operations/country-catalog")
        update_response = await client.post("/api/v1/operations/country-catalog/update")

    assert status_response.status_code == 200
    assert status_response.json()["country_count"] == 242
    assert status_response.json()["next_scheduled_at"] == "2026-09-01T00:00:00Z"
    assert update_response.status_code == 200
    assert update_response.json()["state"] == "updated"
    assert automation.requested == [CountryCatalogUpdateTrigger.MANUAL]
