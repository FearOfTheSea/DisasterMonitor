"""At-least-once ingestion, immutable snapshots, and bounded worker policy."""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol

from disaster_monitor.application.disaster import DisasterQuery, DisasterReport
from disaster_monitor.application.evidence.snapshot_persistence import (
    SnapshotPersistenceService,
)
from disaster_monitor.application.ports.ingest_jobs import IngestJobQueue
from disaster_monitor.application.ports.source_payload import (
    SourcePayloadAcquirer,
)
from disaster_monitor.domain.operations import (
    IngestJob,
    IngestJobStatus,
)


class ScheduledDisasterInvestigator(Protocol):
    """Execute one deterministic, source-bounded disaster investigation."""

    async def execute(self, query: DisasterQuery) -> DisasterReport: ...


@dataclass(frozen=True, slots=True)
class ScheduledInvestigation:
    """One allowlisted recurring query; it carries no action authority."""

    source_id: str
    request_identity: str
    query: DisasterQuery
    interval: timedelta


class IngestionScheduler:
    """Enqueue one idempotent job per recurring-task time bucket."""

    def __init__(
        self,
        repository: IngestJobQueue,
        tasks: tuple[ScheduledInvestigation, ...],
    ) -> None:
        self._repository = repository
        self._tasks = tasks

    async def enqueue_due(self, *, now: datetime) -> int:
        if now.tzinfo is None:
            raise ValueError("Scheduler time must be timezone-aware.")
        created = 0
        for task in self._tasks:
            seconds = int(task.interval.total_seconds())
            if seconds < 60:
                raise ValueError(
                    "Scheduled ingestion intervals must be at least one minute."
                )
            bucket = int(now.timestamp()) // seconds * seconds
            scheduled_for = datetime.fromtimestamp(bucket, tz=UTC)
            job = scheduled_job(
                source_id=task.source_id,
                request_identity=task.request_identity,
                scheduled_for=scheduled_for,
            )
            created += int(await self._repository.enqueue(job))
        return created


class ScheduledInvestigationWorker:
    """Run queued investigations with retry/dead-letter semantics."""

    def __init__(
        self,
        repository: IngestJobQueue,
        investigator: ScheduledDisasterInvestigator,
        tasks: tuple[ScheduledInvestigation, ...],
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._repository = repository
        self._investigator = investigator
        self._queries = {task.request_identity: task.query for task in tasks}
        if len(self._queries) != len(tasks):
            raise ValueError("Scheduled request identities must be unique.")
        self._clock = clock

    async def run_once(self, worker_id: str) -> IngestJob | None:
        now = self._clock()
        job = await self._repository.claim(worker_id, now=now)
        if job is None:
            return None
        query = self._queries.get(job.canonical_request_identity)
        if query is None:
            await self._repository.fail(
                job.job_id,
                failed_at=now,
                error_code="scheduled_request_not_registered",
                retry_at=now,
            )
            return job
        try:
            await self._investigator.execute(query)
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


def scheduled_job(
    *,
    source_id: str,
    request_identity: str,
    scheduled_for: datetime,
    max_attempts: int = 5,
) -> IngestJob:
    """Create a duplicate-safe recurring job identity for one schedule instant."""
    timestamp = scheduled_for.astimezone(UTC).isoformat()
    digest = hashlib.sha256(
        f"{source_id}|{request_identity}|{timestamp}".encode()
    ).hexdigest()[:24]
    return IngestJob(
        job_id=f"ingest-job:{digest}",
        source_id=source_id,
        canonical_request_identity=request_identity,
        scheduled_for=scheduled_for,
        status=IngestJobStatus.QUEUED,
        attempt_count=0,
        max_attempts=max_attempts,
        created_at=scheduled_for,
    )


class IngestionWorker:
    """Claim one durable job, persist evidence, and retry without duplicate state."""

    def __init__(
        self,
        repository: IngestJobQueue,
        persistence: SnapshotPersistenceService,
        acquirers: Mapping[str, SourcePayloadAcquirer],
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._repository = repository
        self._persistence = persistence
        self._acquirers = dict(acquirers)
        self._clock = clock

    async def run_once(self, worker_id: str) -> IngestJob | None:
        now = self._clock()
        job = await self._repository.claim(worker_id, now=now)
        if job is None:
            return None
        acquirer = self._acquirers.get(job.source_id)
        if acquirer is None:
            await self._repository.fail(
                job.job_id,
                failed_at=now,
                error_code="source_not_registered",
                retry_at=now,
            )
            return job
        try:
            payload = await acquirer.acquire(job.canonical_request_identity)
            if payload.source_id != job.source_id:
                raise ValueError("Acquirer source identity escaped its registration.")
            await self._persistence.persist(payload)
        except Exception as error:
            retry_at = now + timedelta(seconds=min(300, 2**job.attempt_count))
            await self._repository.fail(
                job.job_id,
                failed_at=now,
                error_code=_public_error_code(error),
                retry_at=retry_at,
            )
        else:
            await self._repository.complete(job.job_id, completed_at=now)
        return job


def _public_error_code(error: Exception) -> str:
    name = error.__class__.__name__.lower()
    if "timeout" in name:
        return "timeout"
    if isinstance(error, ValueError):
        return "invalid_payload"
    return "provider_failure"
