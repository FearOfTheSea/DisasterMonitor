"""At-least-once ingestion, immutable snapshots, and bounded worker policy."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Protocol

from disaster_monitor.application.incidents.refresh_incident_watch import (
    IncidentWatchRefreshNotFoundError,
    IncidentWatchRefreshRetryableError,
)
from disaster_monitor.application.ingestion.jobs import (
    _public_error_code,
    scheduled_job,
)
from disaster_monitor.application.ports.ingest_jobs import IngestJobQueue
from disaster_monitor.domain.incident_watch import IncidentWatch
from disaster_monitor.domain.operations import (
    IngestJob,
)


class IncidentWatchRefresher(Protocol):
    async def execute(self, watch_id: str) -> object: ...


class IncidentWatchQueueStore(Protocol):
    async def due_watches(self, *, now: datetime) -> tuple[IncidentWatch, ...]: ...

    async def enqueue(self, job: IngestJob) -> bool: ...


class IncidentWatchScheduler:
    """Enqueue due enabled watches into the existing operational queue."""

    source_id = "incident-watch-refresh"

    def __init__(self, store: IncidentWatchQueueStore) -> None:
        self._store = store

    async def enqueue_due(self, *, now: datetime) -> int:
        if now.tzinfo is None:
            raise ValueError("Scheduler time must be timezone-aware.")
        created = 0
        for watch in await self._store.due_watches(now=now):
            job = scheduled_job(
                source_id=self.source_id,
                request_identity=watch.watch_id,
                scheduled_for=watch.next_refresh_at,
            )
            created += int(await self._store.enqueue(job))
        return created


class IncidentWatchWorker:
    """Dispatch claimed queue jobs to deterministic incident-watch refreshes."""

    def __init__(
        self,
        repository: IngestJobQueue,
        refresher: IncidentWatchRefresher,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._repository = repository
        self._refresher = refresher
        self._clock = clock

    async def run_once(self, worker_id: str) -> IngestJob | None:
        now = self._clock()
        job = await self._repository.claim(worker_id, now=now)
        if job is None:
            return None
        if job.source_id != IncidentWatchScheduler.source_id:
            await self._repository.fail(
                job.job_id,
                failed_at=now,
                error_code="scheduled_request_not_registered",
                retry_at=now,
            )
            return job
        try:
            await self._refresher.execute(job.canonical_request_identity)
        except IncidentWatchRefreshNotFoundError:
            await self._repository.complete(job.job_id, completed_at=now)
        except IncidentWatchRefreshRetryableError:
            await self._repository.fail(
                job.job_id,
                failed_at=now,
                error_code="provider_failure",
                retry_at=now + timedelta(seconds=min(300, 2**job.attempt_count)),
            )
        except Exception as error:
            await self._repository.fail(
                job.job_id,
                failed_at=now,
                error_code=_public_error_code(error),
                retry_at=now + timedelta(seconds=min(300, 2**job.attempt_count)),
            )
        else:
            await self._repository.complete(job.job_id, completed_at=now)
        return job
