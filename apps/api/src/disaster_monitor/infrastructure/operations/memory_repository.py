"""Deterministic in-memory operational repository for tests and safe fallback."""

from dataclasses import replace
from datetime import datetime, timedelta

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
    freshness_for,
)


class InMemoryOperationalRepository:
    """Reference implementation with the same idempotency and retry semantics."""

    def __init__(self) -> None:
        self.jobs: dict[str, IngestJob] = {}
        self.snapshot_records: dict[str, SourceSnapshotRecord] = {}
        self.snapshot_idempotency: dict[str, str] = {}
        self.observations: dict[str, NormalizedObservationRecord] = {}
        self.physical_events: dict[str, PhysicalEventRecord] = {}
        self.event_links: dict[tuple[str, str], EventObservationLinkRecord] = {}
        self.world_states: dict[str, WorldStateVersionRecord] = {}
        self.operator_actions: dict[str, OperatorActionRecord] = {}
        self.audit_events: dict[str, AuditEventRecord] = {}

    async def enqueue(self, job: IngestJob) -> bool:
        if job.job_id in self.jobs:
            return False
        self.jobs[job.job_id] = job
        return True

    async def claim(self, worker_id: str, *, now: datetime) -> IngestJob | None:
        eligible = sorted(
            (
                item
                for item in self.jobs.values()
                if item.status in {IngestJobStatus.QUEUED, IngestJobStatus.RETRY}
                and item.scheduled_for <= now
            ),
            key=lambda item: (item.scheduled_for, item.job_id),
        )
        if not eligible:
            return None
        job = eligible[0]
        claimed = replace(
            job,
            status=IngestJobStatus.RUNNING,
            claimed_by=worker_id,
            claimed_at=now,
            attempt_count=job.attempt_count + 1,
        )
        self.jobs[job.job_id] = claimed
        return claimed

    async def complete(self, job_id: str, *, completed_at: datetime) -> None:
        del completed_at
        self.jobs[job_id] = replace(self.jobs[job_id], status=IngestJobStatus.SUCCEEDED)

    async def fail(
        self,
        job_id: str,
        *,
        failed_at: datetime,
        error_code: str,
        retry_at: datetime,
    ) -> IngestJobStatus:
        del failed_at
        job = self.jobs[job_id]
        status = (
            IngestJobStatus.DEAD_LETTER
            if job.attempt_count >= job.max_attempts
            else IngestJobStatus.RETRY
        )
        self.jobs[job_id] = replace(
            job,
            status=status,
            scheduled_for=retry_at,
            claimed_by=None,
            claimed_at=None,
            last_error_code=error_code,
        )
        return status

    async def append_snapshot(self, snapshot: SourceSnapshotRecord) -> bool:
        existing_id = self.snapshot_idempotency.get(snapshot.idempotency_key)
        if existing_id is not None:
            return False
        if snapshot.snapshot_id in self.snapshot_records:
            raise RuntimeError("Snapshot ID maps to different idempotency identity.")
        self.snapshot_records[snapshot.snapshot_id] = snapshot
        self.snapshot_idempotency[snapshot.idempotency_key] = snapshot.snapshot_id
        return True

    async def snapshot_by_idempotency_key(
        self, idempotency_key: str
    ) -> SourceSnapshotRecord | None:
        snapshot_id = self.snapshot_idempotency.get(idempotency_key)
        return self.snapshot_records.get(snapshot_id) if snapshot_id else None

    async def append_observations(
        self, observations: tuple[NormalizedObservationRecord, ...]
    ) -> int:
        inserted = 0
        for observation in observations:
            existing = self.observations.get(observation.observation_id)
            if existing is None:
                if observation.snapshot_id not in self.snapshot_records:
                    raise ValueError("Observation parent snapshot is absent.")
                self.observations[observation.observation_id] = observation
                inserted += 1
            elif existing != observation:
                raise RuntimeError("Observation identity changed after persistence.")
        return inserted

    async def append_world_state(self, state: WorldStateVersionRecord) -> bool:
        existing = self.world_states.get(state.state_version)
        if existing is not None:
            if existing != state:
                raise RuntimeError("World-state version changed after persistence.")
            return False
        self.world_states[state.state_version] = state
        return True

    async def append_physical_event(self, event: PhysicalEventRecord) -> bool:
        existing = self.physical_events.get(event.physical_event_id)
        if existing is not None:
            if existing != event:
                raise RuntimeError("Physical-event identity changed after persistence.")
            return False
        self.physical_events[event.physical_event_id] = event
        return True

    async def append_event_links(
        self, links: tuple[EventObservationLinkRecord, ...]
    ) -> int:
        inserted = 0
        for link in links:
            if link.physical_event_id not in self.physical_events:
                raise ValueError("Event link parent physical event is absent.")
            if link.observation_id not in self.observations:
                raise ValueError("Event link parent observation is absent.")
            key = (link.physical_event_id, link.observation_id)
            existing = self.event_links.get(key)
            if existing is None:
                self.event_links[key] = link
                inserted += 1
            elif existing != link:
                raise RuntimeError("Event-observation link changed after persistence.")
        return inserted

    async def world_state_exists(self, state_version: str) -> bool:
        return state_version in self.world_states

    async def record_operator_action(self, action: OperatorActionRecord) -> bool:
        existing = self.operator_actions.get(action.action_id)
        if existing is not None:
            if existing != action:
                raise RuntimeError("Operator action identity was reused.")
            return False
        self.operator_actions[action.action_id] = action
        return True

    async def append_audit_event(self, event: AuditEventRecord) -> bool:
        existing = self.audit_events.get(event.audit_id)
        if existing is not None:
            if existing != event:
                raise RuntimeError("Audit event identity was reused.")
            return False
        self.audit_events[event.audit_id] = event
        return True

    async def snapshots(
        self, *, source_id: str | None = None, limit: int = 100
    ) -> tuple[SourceSnapshotRecord, ...]:
        selected = (
            item
            for item in self.snapshot_records.values()
            if source_id is None or item.source_id == source_id
        )
        return tuple(
            sorted(
                selected,
                key=lambda item: (item.retrieved_at, item.snapshot_id),
                reverse=True,
            )[:limit]
        )

    async def tombstone_snapshot(
        self,
        snapshot_id: str,
        *,
        deleted_at: datetime,
        reason: str,
    ) -> bool:
        snapshot = self.snapshot_records.get(snapshot_id)
        if snapshot is None:
            raise ValueError("Snapshot does not exist.")
        if snapshot.content_deleted_at is not None:
            return False
        self.snapshot_records[snapshot_id] = replace(
            snapshot,
            content_deleted_at=deleted_at,
            content_deletion_reason=reason,
        )
        return True

    async def freshness(
        self,
        *,
        now: datetime,
        expectations: dict[str, timedelta],
    ) -> tuple[ProviderFreshness, ...]:
        results: list[ProviderFreshness] = []
        for source_id, expectation in sorted(expectations.items()):
            snapshots = await self.snapshots(source_id=source_id, limit=1)
            jobs = sorted(
                (item for item in self.jobs.values() if item.source_id == source_id),
                key=lambda item: (item.claimed_at or item.created_at, item.job_id),
                reverse=True,
            )
            last_job = jobs[0] if jobs else None
            consecutive = 0
            for job in jobs:
                if job.status not in {
                    IngestJobStatus.RETRY,
                    IngestJobStatus.DEAD_LETTER,
                }:
                    break
                consecutive += 1
            results.append(
                freshness_for(
                    source_id=source_id,
                    now=now,
                    expected_freshness=expectation,
                    last_attempt_at=(
                        (last_job.claimed_at or last_job.created_at)
                        if last_job
                        else None
                    ),
                    last_snapshot=snapshots[0] if snapshots else None,
                    consecutive_failures=consecutive,
                    latest_error_code=last_job.last_error_code if last_job else None,
                )
            )
        return tuple(results)

    async def job_status_counts(self) -> dict[IngestJobStatus, int]:
        return {
            status: sum(1 for job in self.jobs.values() if job.status == status)
            for status in IngestJobStatus
        }
