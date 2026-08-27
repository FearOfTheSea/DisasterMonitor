from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from disaster_monitor.application.disaster import DisasterQuery
from disaster_monitor.application.ports.source_payload import (
    AcquiredSourcePayload,
    canonical_request_identity,
)
from disaster_monitor.application.services.evidence_state import (
    build_evidence_world_state,
)
from disaster_monitor.application.services.operational_evidence import (
    OperationalEvidenceRecorder,
)
from disaster_monitor.application.services.operational_ingestion import (
    IngestionScheduler,
    IngestionWorker,
    ScheduledInvestigation,
    ScheduledInvestigationWorker,
    SnapshotPersistenceService,
    record_operator_review,
    scheduled_job,
    snapshot_idempotency_key,
)
from disaster_monitor.application.services.retention import (
    SnapshotRetentionExecutor,
    SnapshotRetentionPolicy,
)
from disaster_monitor.domain.disaster import (
    Disaster,
    DisasterEvent,
    FactStatus,
    ReportedFact,
    SituationReport,
    SourceReference,
)
from disaster_monitor.domain.operations import (
    FreshnessState,
    IngestJobStatus,
    NormalizedObservationRecord,
    OperatorActionRecord,
    OperatorDecision,
)
from disaster_monitor.infrastructure.geography.static_country_catalog import (
    StaticCountryCatalog,
)
from disaster_monitor.infrastructure.operations.filesystem_blob_store import (
    FilesystemBlobStore,
)
from disaster_monitor.infrastructure.operations.memory_repository import (
    InMemoryOperationalRepository,
)
from disaster_monitor.infrastructure.operations.runtime import scheduled_investigations

NOW = datetime(2026, 8, 13, 3, tzinfo=UTC)


class FakeAcquirer:
    def __init__(self, source_id: str = "global-test-source") -> None:
        self.source_id = source_id
        self.calls = 0

    async def acquire(self, request_identity: str) -> AcquiredSourcePayload:
        self.calls += 1
        return AcquiredSourcePayload(
            source_id=self.source_id,
            canonical_request_identity=request_identity,
            provider_revision="bulletin-17",
            content=b"<rss><item>bounded source payload</item></rss>",
            content_type="application/rss+xml",
            response_status=200,
            retrieved_at=NOW,
            published_at=NOW - timedelta(minutes=5),
            observed_at=None,
            rights_id="global-test-terms",
        )


@pytest.mark.asyncio
async def test_worker_is_at_least_once_and_snapshot_persistence_is_idempotent(
    tmp_path: Path,
) -> None:
    repository = InMemoryOperationalRepository()
    blobs = FilesystemBlobStore(tmp_path / "blobs")
    persistence = SnapshotPersistenceService(repository, blobs)
    request = canonical_request_identity("global-test-source", {"feed": "flood"})
    job = scheduled_job(
        source_id="global-test-source",
        request_identity=request,
        scheduled_for=NOW,
    )
    acquirer = FakeAcquirer()
    worker = IngestionWorker(
        repository,
        persistence,
        {"global-test-source": acquirer},
        clock=lambda: NOW,
    )

    assert await repository.enqueue(job)
    assert not await repository.enqueue(job)
    claimed = await worker.run_once("worker-1")
    assert claimed is not None and claimed.job_id == job.job_id
    assert repository.jobs[job.job_id].status == IngestJobStatus.SUCCEEDED
    assert len(repository.snapshot_records) == 1

    acquired = await acquirer.acquire(request)
    duplicate = await persistence.persist(acquired)

    assert len(repository.snapshot_records) == 1
    assert duplicate.payload_sha256.startswith("sha256:")
    assert duplicate.idempotency_key == snapshot_idempotency_key(
        "global-test-source", request, "bulletin-17"
    )
    assert len(list((tmp_path / "blobs").rglob("*.bin"))) == 1

    later = replace(acquired, retrieved_at=NOW + timedelta(minutes=10))
    same_snapshot = await persistence.persist(later)
    assert same_snapshot.retrieved_at == NOW


@pytest.mark.asyncio
async def test_missing_acquirer_dead_letters_without_expanding_authority(
    tmp_path: Path,
) -> None:
    repository = InMemoryOperationalRepository()
    request = canonical_request_identity("unknown-source", {"scope": "bounded"})
    job = scheduled_job(
        source_id="unknown-source",
        request_identity=request,
        scheduled_for=NOW,
        max_attempts=1,
    )
    await repository.enqueue(job)
    worker = IngestionWorker(
        repository,
        SnapshotPersistenceService(repository, FilesystemBlobStore(tmp_path)),
        {},
        clock=lambda: NOW,
    )

    await worker.run_once("worker-1")

    failed = repository.jobs[job.job_id]
    assert failed.status == IngestJobStatus.DEAD_LETTER
    assert failed.last_error_code == "source_not_registered"
    assert not repository.snapshot_records


@pytest.mark.asyncio
async def test_freshness_exposes_stale_and_never_ingested_states(
    tmp_path: Path,
) -> None:
    repository = InMemoryOperationalRepository()
    persistence = SnapshotPersistenceService(
        repository, FilesystemBlobStore(tmp_path / "blobs")
    )
    payload = await FakeAcquirer().acquire("request:global-test-source:test")
    await persistence.persist(payload)

    status = await repository.freshness(
        now=NOW + timedelta(hours=7),
        expectations={
            "global-test-source": timedelta(hours=6),
            "global-test-secondary": timedelta(hours=3),
        },
    )

    by_source = {item.source_id: item for item in status}
    assert by_source["global-test-source"].state == FreshnessState.STALE
    assert by_source["global-test-source"].age_seconds == 7 * 3600 + 5 * 60
    assert by_source["global-test-secondary"].state == (FreshnessState.NEVER_INGESTED)
    assert by_source["global-test-secondary"].age_seconds is None


@pytest.mark.asyncio
async def test_observations_require_snapshot_lineage_and_actions_create_public_audit(
    tmp_path: Path,
) -> None:
    repository = InMemoryOperationalRepository()
    with pytest.raises(ValueError, match="parent snapshot"):
        await repository.append_observations(
            (
                NormalizedObservationRecord(
                    observation_id="observation:missing",
                    snapshot_id="snapshot:missing",
                    source_id="global-test-source",
                    observation_type="official_warning",
                    effective_at=NOW,
                    parser_version="global-test-v1",
                    canonical_json="{}",
                ),
            )
        )
    action = OperatorActionRecord(
        action_id="operator-action:1",
        operator_id="study-local-operator-7",
        decision=OperatorDecision.REVIEWED,
        state_version="state:v1",
        rationale="Reviewed provenance and freshness; no external action was issued.",
        evidence_ids=("observation:1",),
        policy_ids=("human-review-v1",),
        reviewed_at=NOW,
    )

    assert await record_operator_review(repository, action)
    assert not await record_operator_review(repository, action)
    assert repository.audit_events["audit:operator-action:1"].public_rationale
    assert "chain" not in repository.audit_events["audit:operator-action:1"].event_type


def test_blob_deletion_is_scoped_to_configured_root(tmp_path: Path) -> None:
    root = tmp_path / "blobs"
    store = FilesystemBlobStore(root)
    uri = store.put("sha256:" + "a" * 64, b"content")

    store.delete(uri)

    assert not list(root.rglob("*.bin"))
    with pytest.raises(ValueError, match="file URIs"):
        store.delete("https://example.com/not-a-local-blob")


@pytest.mark.asyncio
async def test_evidence_state_persists_only_with_snapshot_lineage(
    tmp_path: Path,
) -> None:
    repository = InMemoryOperationalRepository()
    persistence = SnapshotPersistenceService(
        repository, FilesystemBlobStore(tmp_path / "blobs")
    )
    snapshot = await persistence.persist(await FakeAcquirer().acquire("request:test"))
    country = StaticCountryCatalog().get_by_alpha3("VNM")
    assert country is not None
    source = SourceReference(
        "global-test-source",
        "Global Warnings",
        "Flood bulletin",
        "https://global-warnings.gov.vn/example",
        NOW,
        NOW,
        NOW,
        snapshot_id=snapshot.snapshot_id,
    )
    event = DisasterEvent(
        "global-warnings:event",
        Disaster.FLOOD,
        "Vietnam",
        country,
        NOW,
        source,
    )
    report = SituationReport(
        source,
        "Official warning.",
        (
            ReportedFact(
                "official_warning",
                "Flood warning",
                "Active",
                FactStatus.CONFIRMED,
                source,
            ),
        ),
    )
    state = build_evidence_world_state(event, (report,), evaluated_at=NOW)

    outcome = await OperationalEvidenceRecorder(repository).record(state)
    repeated = await OperationalEvidenceRecorder(repository).record(state)

    assert outcome.persisted and outcome.observation_count == 2
    assert repeated.persisted
    assert await repository.world_state_exists(state.state_version)
    assert len(repository.observations) == 2
    assert len(repository.event_links) == 2

    missing_source = SourceReference(
        "global-test-source",
        "Global Warnings",
        "Uncaptured bulletin",
        "https://global-warnings.gov.vn/uncaptured",
        NOW,
        NOW,
        NOW,
    )
    missing_report = SituationReport(
        missing_source,
        "Not durably captured.",
        (
            ReportedFact(
                "official_warning",
                "Flood warning",
                "Changed",
                FactStatus.CONFIRMED,
                missing_source,
            ),
        ),
    )
    missing_state = build_evidence_world_state(
        event, (missing_report,), evaluated_at=NOW + timedelta(minutes=1)
    )
    skipped = await OperationalEvidenceRecorder(repository).record(missing_state)
    assert not skipped.persisted
    assert skipped.missing_snapshot_observation_ids
    assert not await repository.world_state_exists(missing_state.state_version)


@pytest.mark.asyncio
async def test_scheduler_and_worker_are_duplicate_safe_and_bounded() -> None:
    repository = InMemoryOperationalRepository()
    country = StaticCountryCatalog().get_by_alpha3("VNM")
    assert country is not None
    query = DisasterQuery(
        Disaster.FLOOD,
        country,
        "scheduled",
        ("event_overview",),
        time_window_days=7,
    )
    task = ScheduledInvestigation(
        "global-test-source",
        canonical_request_identity(
            "global-test-source", {"disaster": "flood", "country": "VNM"}
        ),
        query,
        timedelta(minutes=30),
    )
    scheduler = IngestionScheduler(repository, (task,))
    assert await scheduler.enqueue_due(now=NOW) == 1
    assert await scheduler.enqueue_due(now=NOW + timedelta(seconds=20)) == 0

    class Investigator:
        calls = 0

        async def execute(self, query: DisasterQuery):
            self.calls += 1
            assert query.disaster == Disaster.FLOOD
            return object()

    investigator = Investigator()
    worker = ScheduledInvestigationWorker(
        repository, investigator, (task,), clock=lambda: NOW
    )
    claimed = await worker.run_once("worker-1")
    assert claimed is not None
    assert investigator.calls == 1
    assert repository.jobs[claimed.job_id].status == IngestJobStatus.SUCCEEDED


@pytest.mark.asyncio
async def test_retention_deletes_content_but_preserves_provenance(
    tmp_path: Path,
) -> None:
    repository = InMemoryOperationalRepository()
    blobs = FilesystemBlobStore(tmp_path / "blobs")
    snapshot = await SnapshotPersistenceService(repository, blobs).persist(
        await FakeAcquirer().acquire("request:retention")
    )
    result = await SnapshotRetentionExecutor(repository, blobs).execute(
        SnapshotRetentionPolicy(
            source_id=snapshot.source_id,
            rights_id=snapshot.rights_id,
            retain_for=timedelta(days=365),
            deletion_reason="Owner-approved rights retention policy v1.",
        ),
        now=NOW + timedelta(days=366),
    )

    retained = (await repository.snapshots(source_id=snapshot.source_id))[0]
    assert result.tombstoned_snapshot_ids == (snapshot.snapshot_id,)
    assert retained.payload_sha256 == snapshot.payload_sha256
    assert retained.content_deleted_at is not None
    assert not retained.content_available
    assert not list((tmp_path / "blobs").rglob("*.bin"))


def test_scheduled_runtime_has_no_country_scoped_jobs() -> None:
    assert scheduled_investigations() == ()
