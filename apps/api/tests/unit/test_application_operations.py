from datetime import UTC, datetime, timedelta

import pytest

from disaster_monitor.application.services.provider_freshness import (
    ProviderFreshnessService,
)
from disaster_monitor.application.use_cases.record_operator_action import (
    RecordOperatorAction,
    UnknownEvidenceStateError,
)
from disaster_monitor.domain.operations import (
    FreshnessState,
    OperatorDecision,
    SourceSnapshotRecord,
    WorldStateVersionRecord,
)
from disaster_monitor.infrastructure.operations.memory_repository import (
    InMemoryOperationalRepository,
)

NOW = datetime(2026, 8, 13, 8, tzinfo=UTC)


@pytest.mark.asyncio
async def test_provider_freshness_service_owns_expectations_and_clock() -> None:
    repository = InMemoryOperationalRepository()
    await repository.append_snapshot(
        SourceSnapshotRecord(
            snapshot_id="snapshot:usgs",
            idempotency_key="snapshot-key:usgs",
            source_id="usgs-earthquakes",
            canonical_request_identity="request:usgs:test",
            provider_revision="catalog-1",
            retrieved_at=NOW - timedelta(minutes=20),
            published_at=NOW - timedelta(minutes=20),
            observed_at=None,
            response_status=200,
            content_type="application/geo+json",
            payload_sha256="sha256:" + "a" * 64,
            payload_size_bytes=10,
            blob_uri="file:///bounded/snapshot.bin",
            rights_id="usgs-terms",
        )
    )

    values = await ProviderFreshnessService(
        repository,
        expectations={
            "usgs-earthquakes": timedelta(minutes=15),
            "gdacs-tropical-cyclones": timedelta(hours=1),
        },
        clock=lambda: NOW,
    ).list()

    by_source = {item.source_id: item for item in values}
    assert by_source["usgs-earthquakes"].state is FreshnessState.STALE
    assert by_source["usgs-earthquakes"].age_seconds == 20 * 60
    assert by_source["gdacs-tropical-cyclones"].state is (FreshnessState.NEVER_INGESTED)


@pytest.mark.asyncio
async def test_record_operator_action_constructs_and_persists_the_domain_record() -> (
    None
):
    repository = InMemoryOperationalRepository()
    await repository.append_world_state(
        WorldStateVersionRecord(
            "world-state:test",
            "physical-event:test",
            "sha256:" + "a" * 64,
            "sha256:" + "b" * 64,
            "evidence-world-state.v1",
            NOW,
        )
    )
    use_case = RecordOperatorAction(
        repository,
        clock=lambda: NOW,
        identifier=lambda: "fixed-id",
    )

    result = await use_case.execute(
        operator_id="operator-7",
        decision=OperatorDecision.REVIEWED,
        state_version="world-state:test",
        rationale="Checked the source snapshot and freshness.",
        evidence_ids=("snapshot:1", "snapshot:1"),
        policy_ids=("human-review-v1", "human-review-v1"),
    )

    assert result.created
    assert result.action.action_id == "operator-action:fixed-id"
    assert result.action.reviewed_at == NOW
    assert result.action.evidence_ids == ("snapshot:1",)
    assert len(repository.operator_actions) == 1
    assert len(repository.audit_events) == 1


@pytest.mark.asyncio
async def test_record_operator_action_rejects_an_unknown_world_state() -> None:
    use_case = RecordOperatorAction(
        InMemoryOperationalRepository(),
        clock=lambda: NOW,
        identifier=lambda: "fixed-id",
    )

    with pytest.raises(UnknownEvidenceStateError):
        await use_case.execute(
            operator_id="operator-7",
            decision=OperatorDecision.REVIEWED,
            state_version="world-state:missing",
            rationale="Checked the source snapshot and freshness.",
        )
