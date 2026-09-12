"""At-least-once ingestion, immutable snapshots, and bounded worker policy."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Protocol

from disaster_monitor.application.incidents.refresh_incident_watch import (
    IncidentWatchRefreshNotFoundError,
    IncidentWatchRefreshRetryableError,
)
from disaster_monitor.application.ingestion.failure_policy import (
    SCHEDULED_REQUEST_NOT_REGISTERED_ERROR_CODE,
)
from disaster_monitor.application.ingestion.jobs import (
    record_execution_failure,
    record_terminal_failure,
    scheduled_job,
)
from disaster_monitor.application.ingestion.projection_jobs import (
    IncidentProjectionRefresher,
    WorldwideIncidentProjectionScheduler,
)
from disaster_monitor.application.ports.ingest_jobs import IngestJobQueue
from disaster_monitor.domain.incident_watch import IncidentWatch
from disaster_monitor.domain.operations import (
    IngestJob,
)


class IncidentWatchRefresher(Protocol):
    async def execute(self, watch_id: str) -> object: ...


class NewsFeedRefresher(Protocol):
    async def refresh(self) -> object: ...


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
        projection_refresher: IncidentProjectionRefresher | None = None,
        news_refreshers: Mapping[str, NewsFeedRefresher] | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._repository = repository
        self._refresher = refresher
        self._projection_refresher = projection_refresher
        self._news_refreshers = dict(news_refreshers or {})
        self._clock = clock

    async def run_once(self, worker_id: str) -> IngestJob | None:
        now = self._clock()
        job = await self._repository.claim(worker_id, now=now)
        if job is None:
            return None
        if job.source_id == WorldwideIncidentProjectionScheduler.source_id:
            if self._projection_refresher is None:
                await record_terminal_failure(
                    self._repository,
                    job,
                    failed_at=now,
                    error_code="projection_refresher_not_registered",
                )
                return job
            try:
                await self._projection_refresher.refresh()
            except Exception as error:
                await record_execution_failure(
                    self._repository, job, failed_at=now, error=error
                )
            else:
                await self._repository.complete(job.job_id, completed_at=now)
            return job
        news_refresher = self._news_refreshers.get(job.source_id)
        if news_refresher is not None:
            try:
                await news_refresher.refresh()
            except Exception as error:
                await record_execution_failure(
                    self._repository, job, failed_at=now, error=error
                )
            else:
                await self._repository.complete(job.job_id, completed_at=now)
            return job
        if job.source_id != IncidentWatchScheduler.source_id:
            await record_terminal_failure(
                self._repository,
                job,
                failed_at=now,
                error_code=SCHEDULED_REQUEST_NOT_REGISTERED_ERROR_CODE,
            )
            return job
        try:
            await self._refresher.execute(job.canonical_request_identity)
        except IncidentWatchRefreshNotFoundError:
            await self._repository.complete(job.job_id, completed_at=now)
        except IncidentWatchRefreshRetryableError as error:
            await record_execution_failure(
                self._repository, job, failed_at=now, error=error
            )
        except Exception as error:
            await record_execution_failure(
                self._repository, job, failed_at=now, error=error
            )
        else:
            await self._repository.complete(job.job_id, completed_at=now)
        return job
