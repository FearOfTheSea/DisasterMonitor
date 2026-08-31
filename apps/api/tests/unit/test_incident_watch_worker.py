from datetime import UTC, datetime, timedelta

import pytest

from disaster_monitor.application.services.operational_ingestion import (
    IncidentWatchScheduler,
    IncidentWatchWorker,
)
from disaster_monitor.application.use_cases.refresh_incident_watch import (
    IncidentWatchRefreshRetryableError,
)
from disaster_monitor.domain.disaster import (
    Disaster,
    IncidentWatch,
    IncidentWatchScope,
)
from disaster_monitor.domain.operations import IngestJobStatus
from disaster_monitor.infrastructure.operations.memory_repository import (
    InMemoryOperationalRepository,
)

NOW = datetime(2026, 8, 31, 8, tzinfo=UTC)


def watch() -> IncidentWatch:
    return IncidentWatch(
        watch_id="incident-watch:scheduled",
        disaster=Disaster.FLOOD,
        scope=IncidentWatchScope.worldwide(),
        enabled=True,
        refresh_interval_seconds=900,
        created_at=NOW,
        updated_at=NOW,
        next_refresh_at=NOW,
    )


@pytest.mark.asyncio
async def test_watch_scheduler_enqueues_due_watches_once_per_refresh_bucket() -> None:
    repository = InMemoryOperationalRepository()
    await repository.create_watch(watch())
    scheduler = IncidentWatchScheduler(repository)

    assert await scheduler.enqueue_due(now=NOW) == 1
    assert await scheduler.enqueue_due(now=NOW) == 0
    queued = next(iter(repository.jobs.values()))
    assert queued.source_id == "incident-watch-refresh"
    assert queued.canonical_request_identity == watch().watch_id


@pytest.mark.asyncio
async def test_watch_worker_retries_provider_failure_and_completes_success() -> None:
    repository = InMemoryOperationalRepository()
    await repository.create_watch(watch())
    await IncidentWatchScheduler(repository).enqueue_due(now=NOW)

    class Refresh:
        calls = 0

        async def execute(self, watch_id: str):
            self.calls += 1
            assert watch_id == watch().watch_id
            if self.calls == 1:
                raise IncidentWatchRefreshRetryableError("provider timeout")
            return object()

    refresh = Refresh()
    current = NOW
    worker = IncidentWatchWorker(repository, refresh, clock=lambda: current)

    first = await worker.run_once("worker-1")
    assert first is not None
    assert repository.jobs[first.job_id].status is IngestJobStatus.RETRY
    current += timedelta(seconds=2)
    second = await worker.run_once("worker-1")
    assert second is not None
    assert repository.jobs[first.job_id].status is IngestJobStatus.SUCCEEDED
    assert refresh.calls == 2
