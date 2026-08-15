"""Ports for durable evidence snapshots, jobs, history, and attribution."""

from datetime import datetime, timedelta
from typing import Protocol

from disaster_monitor.domain.operations import (
    AuditEventRecord,
    EventObservationLinkRecord,
    IngestJob,
    IngestJobStatus,
    NormalizedObservationRecord,
    OperatorActionRecord,
    PhysicalEventRecord,
    ProviderFreshness,
    SourceSnapshotRecord,
    WorldStateVersionRecord,
)


class ImmutableBlobStore(Protocol):
    """Content-addressed payload storage with explicit retention deletion."""

    def put(self, payload_sha256: str, content: bytes) -> str: ...

    def delete(self, blob_uri: str) -> None: ...


class OperationalRepository(Protocol):
    """Transactional persistent state required by the operational roadmap."""

    async def enqueue(self, job: IngestJob) -> bool: ...

    async def claim(self, worker_id: str, *, now: datetime) -> IngestJob | None: ...

    async def complete(self, job_id: str, *, completed_at: datetime) -> None: ...

    async def fail(
        self,
        job_id: str,
        *,
        failed_at: datetime,
        error_code: str,
        retry_at: datetime,
    ) -> IngestJobStatus: ...

    async def append_snapshot(self, snapshot: SourceSnapshotRecord) -> bool: ...

    async def snapshot_by_idempotency_key(
        self, idempotency_key: str
    ) -> SourceSnapshotRecord | None: ...

    async def append_observations(
        self, observations: tuple[NormalizedObservationRecord, ...]
    ) -> int: ...

    async def append_physical_event(self, event: PhysicalEventRecord) -> bool: ...

    async def append_event_links(
        self, links: tuple[EventObservationLinkRecord, ...]
    ) -> int: ...

    async def append_world_state(self, state: WorldStateVersionRecord) -> bool: ...

    async def world_state_exists(self, state_version: str) -> bool: ...

    async def record_operator_action(self, action: OperatorActionRecord) -> bool: ...

    async def append_audit_event(self, event: AuditEventRecord) -> bool: ...

    async def snapshots(
        self, *, source_id: str | None = None, limit: int = 100
    ) -> tuple[SourceSnapshotRecord, ...]: ...

    async def tombstone_snapshot(
        self,
        snapshot_id: str,
        *,
        deleted_at: datetime,
        reason: str,
    ) -> bool: ...

    async def freshness(
        self,
        *,
        now: datetime,
        expectations: dict[str, timedelta],
    ) -> tuple[ProviderFreshness, ...]: ...

    async def job_status_counts(self) -> dict[IngestJobStatus, int]: ...
