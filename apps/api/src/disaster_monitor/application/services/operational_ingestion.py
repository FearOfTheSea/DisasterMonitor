"""At-least-once ingestion, immutable snapshots, and bounded worker policy."""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol

from disaster_monitor.application.disaster import DisasterQuery, DisasterReport
from disaster_monitor.application.ports.operational_state import (
    ImmutableBlobStore,
    OperationalRepository,
)
from disaster_monitor.domain.operations import (
    AuditEventRecord,
    IngestJob,
    IngestJobStatus,
    OperatorActionRecord,
    SourceSnapshotRecord,
)


@dataclass(frozen=True, slots=True)
class AcquiredSourcePayload:
    """One bounded successful response prior to immutable persistence."""

    source_id: str
    canonical_request_identity: str
    provider_revision: str | None
    content: bytes
    content_type: str
    response_status: int
    retrieved_at: datetime
    published_at: datetime | None
    observed_at: datetime | None
    rights_id: str


class SourcePayloadAcquirer(Protocol):
    """Fetch one allowlisted request without deciding source authority."""

    async def acquire(
        self, canonical_request_identity: str
    ) -> AcquiredSourcePayload: ...


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
        repository: OperationalRepository,
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
        repository: OperationalRepository,
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


def canonical_request_identity(source_id: str, parameters: Mapping[str, str]) -> str:
    """Build a stable request identity without retaining credentials."""
    material = "&".join(
        f"{key}={parameters[key]}" for key in sorted(parameters) if parameters[key]
    )
    digest = hashlib.sha256(f"{source_id}|{material}".encode()).hexdigest()
    return f"request:{source_id}:{digest}"


def snapshot_idempotency_key(
    source_id: str,
    request_identity: str,
    provider_revision_or_payload_hash: str,
) -> str:
    """Use the roadmap's source + request + revision/payload identity."""
    material = "|".join(
        (source_id, request_identity, provider_revision_or_payload_hash)
    )
    return "sha256:" + hashlib.sha256(material.encode()).hexdigest()


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


class SnapshotPersistenceService:
    """Persist payload bytes before exposing normalized evidence downstream."""

    def __init__(
        self, repository: OperationalRepository, blob_store: ImmutableBlobStore
    ) -> None:
        self._repository = repository
        self._blob_store = blob_store

    async def persist(self, payload: AcquiredSourcePayload) -> SourceSnapshotRecord:
        if not payload.content:
            raise ValueError("An empty provider response cannot become evidence.")
        checksum = "sha256:" + hashlib.sha256(payload.content).hexdigest()
        revision = payload.provider_revision or checksum
        idempotency = snapshot_idempotency_key(
            payload.source_id, payload.canonical_request_identity, revision
        )
        existing = await self._repository.snapshot_by_idempotency_key(idempotency)
        if existing is not None:
            return existing
        snapshot_id = f"source-snapshot:{idempotency.removeprefix('sha256:')[:24]}"
        blob_uri = self._blob_store.put(checksum, payload.content)
        snapshot = SourceSnapshotRecord(
            snapshot_id=snapshot_id,
            idempotency_key=idempotency,
            source_id=payload.source_id,
            canonical_request_identity=payload.canonical_request_identity,
            provider_revision=revision,
            retrieved_at=payload.retrieved_at,
            published_at=payload.published_at,
            observed_at=payload.observed_at,
            response_status=payload.response_status,
            content_type=payload.content_type,
            payload_sha256=checksum,
            payload_size_bytes=len(payload.content),
            blob_uri=blob_uri,
            rights_id=payload.rights_id,
        )
        created = await self._repository.append_snapshot(snapshot)
        if created:
            return snapshot
        existing = await self._repository.snapshot_by_idempotency_key(idempotency)
        if existing is None:
            raise RuntimeError("Snapshot idempotency conflict could not be resolved.")
        return existing


class IngestionWorker:
    """Claim one durable job, persist evidence, and retry without duplicate state."""

    def __init__(
        self,
        repository: OperationalRepository,
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


async def record_operator_review(
    repository: OperationalRepository,
    action: OperatorActionRecord,
) -> bool:
    """Persist an attributable review and its public audit projection."""
    created = await repository.record_operator_action(action)
    if created:
        await repository.append_audit_event(
            AuditEventRecord(
                audit_id=f"audit:{action.action_id}",
                event_type="operator_review_recorded",
                subject_id=action.state_version,
                occurred_at=action.reviewed_at,
                evidence_ids=action.evidence_ids,
                policy_ids=action.policy_ids,
                public_rationale=action.rationale,
            )
        )
    return created


def _public_error_code(error: Exception) -> str:
    name = error.__class__.__name__.lower()
    if "timeout" in name:
        return "timeout"
    if isinstance(error, ValueError):
        return "invalid_payload"
    return "provider_failure"
