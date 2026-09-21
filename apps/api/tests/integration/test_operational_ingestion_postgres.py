import asyncio
import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import psycopg
import pytest

from disaster_monitor.application.ports.ground_imagery.jobs import (
    GroundImageryJobStatus,
    preparation_job,
)
from disaster_monitor.application.ports.incident_projection import (
    IncidentProjectionRecord,
)
from disaster_monitor.application.ports.ingest_jobs import IngestJobQueue
from disaster_monitor.application.ports.provider_budget import ProviderBudgetExceeded
from disaster_monitor.domain.imagery.observations import Sensor, TemporalRole
from disaster_monitor.domain.operations import (
    AuditEventRecord,
    EventObservationLinkRecord,
    IngestJob,
    IngestJobStatus,
    NormalizedObservationRecord,
    OperatorActionRecord,
    OperatorDecision,
    PhysicalEventRecord,
    ProviderAttempt,
    ProviderAttemptOutcome,
    SourceSnapshotRecord,
    WorldStateVersionRecord,
)
from disaster_monitor.infrastructure.ground_imagery.postgres_jobs import (
    PostgresGroundImageryJobQueue,
)
from disaster_monitor.infrastructure.operations.memory_repository import (
    InMemoryOperationalRepository,
)
from disaster_monitor.infrastructure.operations.postgres_provider_budget import (
    PostgresProviderBudgetLedger,
)
from disaster_monitor.infrastructure.operations.postgres_repository import (
    PostgresOperationalRepository,
)

NOW = datetime(2026, 9, 1, 12, tzinfo=UTC)


def _job() -> IngestJob:
    identity = uuid4().hex
    return IngestJob(
        job_id=f"ingest-job:adapter-contract:{identity}",
        source_id=f"adapter-contract-source:{identity}",
        canonical_request_identity=f"request:adapter-contract:{identity}",
        scheduled_for=NOW,
        status=IngestJobStatus.QUEUED,
        attempt_count=0,
        max_attempts=3,
        created_at=NOW,
    )


async def _exercise_queue(queue: IngestJobQueue) -> tuple[object, ...]:
    job = _job()
    assert await queue.enqueue(job)
    claimed = await queue.claim("adapter-contract-worker", now=NOW)
    assert claimed is not None
    retry_at = NOW + timedelta(seconds=2)
    retry_status = await queue.fail(
        job.job_id,
        failed_at=NOW,
        error_code="provider_failure",
        retry_at=retry_at,
    )
    retried = await queue.claim("adapter-contract-worker", now=retry_at)
    assert retried is not None
    terminal_status = await queue.fail(
        job.job_id,
        failed_at=retry_at,
        error_code="invalid_payload",
        retry_at=None,
    )
    return (
        retry_status,
        retried.scheduled_for,
        retried.attempt_count,
        terminal_status,
    )


@pytest.mark.asyncio
@pytest.mark.postgres
async def test_memory_and_postgres_queues_agree_on_retry_and_terminal_failure(
    postgres_dsn: str,
) -> None:
    postgres = PostgresOperationalRepository(postgres_dsn)
    await postgres.migrate()

    memory_result = await _exercise_queue(InMemoryOperationalRepository())
    postgres_result = await _exercise_queue(postgres)

    assert (
        memory_result
        == postgres_result
        == (
            IngestJobStatus.RETRY,
            NOW + timedelta(seconds=2),
            2,
            IngestJobStatus.DEAD_LETTER,
        )
    )


@pytest.mark.asyncio
@pytest.mark.postgres
async def test_postgres_ingestion_preserves_evidence_and_audit_semantics(
    postgres_dsn: str,
) -> None:
    repository = PostgresOperationalRepository(postgres_dsn)
    await repository.migrate()
    identity = uuid4().hex
    source_id = f"ingestion-contract-source:{identity}"
    snapshot = SourceSnapshotRecord(
        snapshot_id=f"snapshot:ingestion-contract:{identity}",
        idempotency_key=f"snapshot-key:ingestion-contract:{identity}",
        source_id=source_id,
        canonical_request_identity=f"request:ingestion-contract:{identity}",
        provider_revision="fixture-revision-1",
        retrieved_at=NOW,
        published_at=NOW,
        observed_at=None,
        response_status=200,
        content_type="application/json",
        payload_sha256="sha256:" + "a" * 64,
        payload_size_bytes=2,
        blob_uri=f"file:///tmp/ingestion-contract-{identity}.json",
        rights_id="fixture-rights-v1",
    )
    observation = NormalizedObservationRecord(
        observation_id=f"observation:ingestion-contract:{identity}",
        snapshot_id=snapshot.snapshot_id,
        source_id=source_id,
        observation_type="official_warning",
        effective_at=NOW,
        parser_version="fixture-parser-v1",
        canonical_json='{"status":"active"}',
    )
    physical_event = PhysicalEventRecord(
        physical_event_id=f"physical-event:ingestion-contract:{identity}",
        disaster="flood",
        country_code="VNM",
        latitude=10.5,
        longitude=106.5,
        created_at=NOW,
    )
    world_state = WorldStateVersionRecord(
        state_version=f"world-state:ingestion-contract:{identity}",
        physical_event_id=physical_event.physical_event_id,
        source_set_sha256="sha256:" + "b" * 64,
        canonical_state_sha256="sha256:" + "c" * 64,
        policy_version="evidence-world-state.v1",
        created_at=NOW,
    )

    assert await repository.append_snapshot(snapshot)
    assert not await repository.append_snapshot(snapshot)
    assert (
        await repository.snapshot_by_idempotency_key(snapshot.idempotency_key)
        == snapshot
    )
    assert await repository.append_observations((observation,)) == 1
    assert await repository.append_observations((observation,)) == 0
    assert await repository.append_physical_event(physical_event)
    assert await repository.append_world_state(world_state)
    assert (
        await repository.append_event_links(
            (
                EventObservationLinkRecord(
                    physical_event_id=physical_event.physical_event_id,
                    observation_id=observation.observation_id,
                    assignment_status="assigned",
                    rationale="The source snapshot and event identity agree.",
                ),
            )
        )
        == 1
    )
    assert (
        await repository.append_event_links(
            (
                EventObservationLinkRecord(
                    physical_event_id=physical_event.physical_event_id,
                    observation_id=observation.observation_id,
                    assignment_status="assigned",
                    rationale="The source snapshot and event identity agree.",
                ),
            )
        )
        == 0
    )
    assert await repository.world_state_exists(world_state.state_version)

    await repository.record_provider_attempt(
        ProviderAttempt(
            source_id=source_id,
            attempted_at=NOW + timedelta(minutes=1),
            outcome=ProviderAttemptOutcome.FAILED,
            reason_code="provider_failure",
            retryable=True,
            http_status=503,
        )
    )
    freshness = await repository.freshness(
        now=NOW + timedelta(hours=2),
        expectations={source_id: timedelta(hours=1)},
    )
    assert freshness[0].state.value == "stale"
    assert freshness[0].last_success_at == NOW
    assert freshness[0].consecutive_failures == 1
    assert freshness[0].latest_error_code == "provider_failure"

    action = OperatorActionRecord(
        action_id=f"operator-action:ingestion-contract:{identity}",
        operator_id="fixture-operator",
        decision=OperatorDecision.REVIEWED,
        state_version=world_state.state_version,
        rationale="Reviewed the source lineage and provider freshness.",
        evidence_ids=(observation.observation_id,),
        policy_ids=("human-review-v1",),
        reviewed_at=NOW,
    )
    assert await repository.record_operator_action(action)
    assert not await repository.record_operator_action(action)
    audit = AuditEventRecord(
        audit_id=f"audit:ingestion-contract:{identity}",
        event_type="operator_review",
        subject_id=world_state.state_version,
        occurred_at=NOW,
        evidence_ids=(observation.observation_id,),
        policy_ids=("human-review-v1",),
        public_rationale="Operator review recorded for the evidence world state.",
    )
    assert await repository.append_audit_event(audit)
    assert not await repository.append_audit_event(audit)

    projection_time = datetime.now(UTC)
    projection = IncidentProjectionRecord(
        projection_id=f"incident-projection:ingestion-contract:{identity}",
        snapshot_version=f"projection-version:ingestion-contract:{identity}",
        retrieved_at=projection_time,
        created_at=projection_time,
        payload_json='{"incidents":[]}',
    )
    assert await repository.append_incident_projection(projection)
    assert not await repository.append_incident_projection(projection)
    latest_projection = await repository.latest_incident_projection()
    assert latest_projection is not None
    assert latest_projection.projection_id == projection.projection_id
    assert latest_projection.snapshot_version == projection.snapshot_version
    assert latest_projection.retrieved_at == projection.retrieved_at
    assert latest_projection.created_at == projection.created_at
    assert json.loads(latest_projection.payload_json) == {"incidents": []}


@pytest.mark.asyncio
@pytest.mark.postgres
async def test_postgres_provider_budget_counts_settled_calls(
    postgres_dsn: str,
) -> None:
    repository = PostgresOperationalRepository(postgres_dsn)
    await repository.migrate()
    ledger = PostgresProviderBudgetLedger(postgres_dsn)
    provider_id = f"budget-contract:{uuid4().hex}"

    for _ in range(2):
        reservation = await ledger.reserve(
            provider_id,
            worker_id="budget-worker",
            estimated_units=1,
            limit_units=2,
            now=NOW,
        )
        await ledger.settle(reservation.reservation_id, actual_units=1, now=NOW)

    with pytest.raises(ProviderBudgetExceeded, match="budget exhausted"):
        await ledger.reserve(
            provider_id,
            worker_id="budget-worker",
            estimated_units=1,
            limit_units=2,
            now=NOW,
        )
    status = await ledger.status(now=NOW)
    matching = next(item for item in status if item.provider_id == provider_id)
    assert matching.settled_units == 2
    assert matching.remaining_units == 0


@pytest.mark.asyncio
@pytest.mark.postgres
async def test_postgres_ground_jobs_serialize_per_request_and_fence_old_worker(
    postgres_dsn: str,
) -> None:
    repository = PostgresOperationalRepository(postgres_dsn)
    await repository.migrate()
    queue = PostgresGroundImageryJobQueue(postgres_dsn)
    request_id = f"ground-contract:{uuid4().hex}"
    async with await psycopg.AsyncConnection.connect(postgres_dsn) as connection:
        await connection.execute(
            """
            INSERT INTO imagery_requests(
                request_id, incident_id, owner_scope, request_version,
                reference_time, state, payload, created_at, updated_at
            ) VALUES (%s,%s,'test',1,%s,'queued','{}'::jsonb,%s,%s)
            """,
            (request_id, request_id, NOW, NOW, NOW),
        )
    try:
        for role in (
            TemporalRole.PRE_EVENT_REFERENCE,
            TemporalRole.LATEST_USEFUL,
        ):
            assert await queue.enqueue(
                preparation_job(
                    request_id=request_id,
                    request_version=1,
                    sensor=Sensor.SENTINEL_1,
                    role=role,
                    overview=True,
                    output_kind=None,
                    now=NOW,
                )
            )

        concurrent = await asyncio.gather(
            queue.claim("worker-one", now=NOW, lease_seconds=60),
            queue.claim("worker-two", now=NOW, lease_seconds=60),
        )
        claimed = tuple(item for item in concurrent if item is not None)
        assert len(claimed) == 1
        first = claimed[0]
        reclaimed = await queue.claim(
            "worker-two", now=NOW + timedelta(seconds=61), lease_seconds=60
        )
        assert reclaimed is not None
        assert reclaimed.job_id == first.job_id
        assert reclaimed.fencing_token == first.fencing_token + 1
        with pytest.raises(RuntimeError, match="fencing token"):
            await queue.complete(
                first.job_id,
                completed_at=NOW + timedelta(seconds=62),
                fencing_token=first.fencing_token,
            )
        failed = await queue.fail(
            reclaimed.job_id,
            failed_at=NOW + timedelta(seconds=62),
            fencing_token=reclaimed.fencing_token,
            error_code="ground_preparation_failed",
            error_detail="Stored Ground request metadata is invalid.",
            retry_at=None,
        )
        assert failed.status is GroundImageryJobStatus.FAILED
        assert failed.diagnostic == "Stored Ground request metadata is invalid."
    finally:
        async with await psycopg.AsyncConnection.connect(postgres_dsn) as connection:
            await connection.execute(
                "DELETE FROM imagery_requests WHERE request_id = %s", (request_id,)
            )
