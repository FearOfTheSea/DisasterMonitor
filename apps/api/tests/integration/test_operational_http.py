from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
from conftest import FakeLanguageModel

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


@pytest.mark.asyncio
async def test_operational_status_history_and_attributed_review(tmp_path: Path) -> None:
    repository = InMemoryOperationalRepository()
    snapshot = await SnapshotPersistenceService(
        repository, FilesystemBlobStore(tmp_path / "blobs")
    ).persist(
        AcquiredSourcePayload(
            source_id="nchmf-vietnam-warnings",
            canonical_request_identity="request:nchmf-vietnam-warnings:test",
            provider_revision="warning-1",
            content=b"bounded warning",
            content_type="application/rss+xml",
            response_status=200,
            retrieved_at=NOW,
            published_at=NOW,
            observed_at=None,
            rights_id="nchmf-rss-terms-2026-08",
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
        review = await client.post(
            "/api/v1/operations/operator-actions",
            headers={"x-disastermonitor-operator": "operator-7"},
            json={
                "state_version": world_state.state_version,
                "decision": "reviewed",
                "rationale": "Checked the source snapshot and freshness.",
                "evidence_ids": [snapshot.snapshot_id],
                "policy_ids": ["human-review-v1"],
            },
        )

    assert providers.status_code == 200
    assert len(providers.json()) == 9
    by_source = {item["source_id"]: item for item in providers.json()}
    assert by_source["nchmf-vietnam-warnings"]["last_success_at"] is not None
    assert history.status_code == 200
    assert history.json()[0]["snapshot_id"] == snapshot.snapshot_id
    assert "blob_uri" not in history.json()[0]
    assert history.json()[0]["content_available"] is True
    assert metrics.status_code == 200
    assert "disastermonitor_http_requests_total" in metrics.text
    assert 'disastermonitor_ingest_jobs{status="queued"} 0.0' in metrics.text
    assert missing_identity.status_code == 401
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
