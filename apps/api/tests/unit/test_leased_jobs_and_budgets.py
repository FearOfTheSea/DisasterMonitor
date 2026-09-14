import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from disaster_monitor.application.ground_imagery.jobs import GroundImageryWorker
from disaster_monitor.application.ingestion.jobs import scheduled_job
from disaster_monitor.application.ports.ground_imagery.jobs import (
    GroundImageryJobStatus,
    preparation_job,
)
from disaster_monitor.application.ports.provider_budget import ProviderBudgetExceeded
from disaster_monitor.domain.imagery.observations import Sensor, TemporalRole
from disaster_monitor.domain.operations import IngestJobStatus
from disaster_monitor.infrastructure.ground_imagery.memory_jobs import (
    InMemoryGroundImageryJobQueue,
)
from disaster_monitor.infrastructure.operations.memory_provider_budget import (
    InMemoryProviderBudgetLedger,
)
from disaster_monitor.infrastructure.operations.memory_repository import (
    InMemoryOperationalRepository,
)

NOW = datetime(2026, 9, 13, 10, tzinfo=UTC)


@pytest.mark.asyncio
async def test_ingest_lease_expiry_fences_old_worker_and_dead_letters_at_limit() -> (
    None
):
    repository = InMemoryOperationalRepository()
    job = scheduled_job(
        source_id="fixture-source",
        request_identity="fixture-request",
        scheduled_for=NOW,
        max_attempts=2,
    )
    assert await repository.enqueue(job)
    first = await repository.claim("worker-one", now=NOW, lease_seconds=60)
    assert first is not None
    second = await repository.claim(
        "worker-two", now=NOW + timedelta(seconds=61), lease_seconds=60
    )
    assert second is not None
    assert second.fencing_token == first.fencing_token + 1
    with pytest.raises(RuntimeError, match="fencing token"):
        await repository.complete(
            job.job_id,
            completed_at=NOW + timedelta(seconds=62),
            fencing_token=first.fencing_token,
        )
    await repository.fail(
        job.job_id,
        failed_at=NOW + timedelta(seconds=62),
        error_code="fixture_failure",
        retry_at=NOW + timedelta(seconds=90),
        fencing_token=second.fencing_token,
        error_detail="bounded diagnostic",
    )
    assert repository.jobs[job.job_id].status is IngestJobStatus.DEAD_LETTER
    assert repository.jobs[job.job_id].diagnostic == "bounded diagnostic"


@pytest.mark.asyncio
async def test_ground_worker_retries_provider_failure_and_preserves_fencing() -> None:
    queue = InMemoryGroundImageryJobQueue()
    job = preparation_job(
        request_id="ground-request",
        request_version=1,
        sensor=Sensor.SENTINEL_1,
        role=TemporalRole.LATEST_USEFUL,
        overview=True,
        output_kind=None,
        now=NOW,
        max_attempts=2,
    )
    await queue.enqueue(job)

    class FailingExecutor:
        async def execute_preparation_job(self, claimed_job):
            raise ValueError("fixture renderer failed")

        async def mark_preparation_failed(self, request_id: str, *, detail: str):
            return None

    worker = GroundImageryWorker(queue, FailingExecutor(), clock=lambda: NOW)
    claimed = await worker.run_once("ground-worker")

    assert claimed is not None
    stored = queue.jobs[job.job_id]
    assert stored.status is GroundImageryJobStatus.RETRY_WAIT
    assert stored.fencing_token == 1
    assert stored.diagnostic == "fixture renderer failed"


@pytest.mark.asyncio
async def test_ground_worker_renews_lease_while_preparation_is_running() -> None:
    queue = InMemoryGroundImageryJobQueue()
    started_at = datetime.now(UTC)
    job = preparation_job(
        request_id="slow-ground-request",
        request_version=1,
        sensor=Sensor.SENTINEL_1,
        role=TemporalRole.LATEST_USEFUL,
        overview=True,
        output_kind=None,
        now=started_at,
    )
    await queue.enqueue(job)

    class SlowExecutor:
        async def execute_preparation_job(self, claimed_job):
            await asyncio.sleep(1.2)

        async def mark_preparation_failed(self, request_id: str, *, detail: str):
            return None

    worker = GroundImageryWorker(queue, SlowExecutor(), lease_seconds=1)
    running = asyncio.create_task(worker.run_once("ground-worker"))
    await asyncio.sleep(1.05)

    duplicate = await queue.claim("second-worker", now=datetime.now(UTC))
    assert duplicate is None
    await running
    assert queue.jobs[job.job_id].status is GroundImageryJobStatus.SUCCEEDED


@pytest.mark.asyncio
async def test_ground_queue_serializes_jobs_for_the_same_request() -> None:
    queue = InMemoryGroundImageryJobQueue()
    for role in (
        TemporalRole.PRE_EVENT_REFERENCE,
        TemporalRole.LATEST_USEFUL,
    ):
        await queue.enqueue(
            preparation_job(
                request_id="ground-request",
                request_version=1,
                sensor=Sensor.SENTINEL_1,
                role=role,
                overview=True,
                output_kind=None,
                now=NOW,
            )
        )

    first = await queue.claim("worker-one", now=NOW, lease_seconds=60)
    assert first is not None
    assert await queue.claim("worker-two", now=NOW, lease_seconds=60) is None

    await queue.complete(
        first.job_id,
        completed_at=NOW + timedelta(seconds=1),
        fencing_token=first.fencing_token,
    )
    second = await queue.claim(
        "worker-two", now=NOW + timedelta(seconds=1), lease_seconds=60
    )
    assert second is not None
    assert second.request_id == first.request_id
    assert second.job_id != first.job_id


@pytest.mark.asyncio
async def test_provider_budget_settlement_uses_original_window_after_clock_rollover():
    ledger = InMemoryProviderBudgetLedger()
    reservation = await ledger.reserve(
        "copernicus-data-space-ground",
        worker_id="worker",
        estimated_units=1,
        limit_units=2,
        now=NOW,
    )
    await ledger.settle(
        reservation.reservation_id,
        actual_units=1,
        now=NOW + timedelta(hours=2),
    )

    status = await ledger.status(now=NOW + timedelta(hours=2))
    assert status == ()


@pytest.mark.asyncio
async def test_provider_budget_counts_settled_calls_against_window_limit() -> None:
    ledger = InMemoryProviderBudgetLedger()
    for _ in range(2):
        reservation = await ledger.reserve(
            "copernicus-data-space-ground",
            worker_id="worker",
            estimated_units=1,
            limit_units=2,
            now=NOW,
        )
        await ledger.settle(reservation.reservation_id, actual_units=1, now=NOW)

    with pytest.raises(ProviderBudgetExceeded, match="budget exhausted"):
        await ledger.reserve(
            "copernicus-data-space-ground",
            worker_id="worker",
            estimated_units=1,
            limit_units=2,
            now=NOW,
        )

    status = await ledger.status(now=NOW)
    assert status[0].settled_units == 2
    assert status[0].remaining_units == 0


def test_ground_job_identity_includes_request_version_and_role() -> None:
    first = preparation_job(
        request_id="ground-request",
        request_version=1,
        sensor=Sensor.SENTINEL_1,
        role=TemporalRole.LATEST_USEFUL,
        overview=True,
        output_kind="numeric",
        now=NOW,
    )
    second = preparation_job(
        request_id="ground-request",
        request_version=2,
        sensor=Sensor.SENTINEL_1,
        role=TemporalRole.LATEST_USEFUL,
        overview=True,
        output_kind="numeric",
        now=NOW,
    )
    assert first.job_id != second.job_id
