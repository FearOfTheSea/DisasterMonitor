"""Deterministic in-memory operational repository for tests and safe fallback."""

from dataclasses import replace
from datetime import datetime, timedelta

from disaster_monitor.domain.disaster import (
    IncidentWatch,
    IncidentWatchChange,
    IncidentWatchObservation,
)
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
        self.incident_watches: dict[str, IncidentWatch] = {}
        self.watch_observations: dict[str, IncidentWatchObservation] = {}
        self.watch_latest_observation: dict[str, str] = {}
        self.watch_latest_successful_observation: dict[str, str] = {}
        self.watch_change_records: dict[str, IncidentWatchChange] = {}

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

    async def create_watch(self, watch: IncidentWatch) -> bool:
        if watch.watch_id in self.incident_watches:
            return False
        self.incident_watches[watch.watch_id] = watch
        return True

    async def list_watches(self) -> tuple[IncidentWatch, ...]:
        return tuple(
            sorted(
                self.incident_watches.values(),
                key=lambda item: (item.created_at, item.watch_id),
                reverse=True,
            )
        )

    async def get_watch(self, watch_id: str) -> IncidentWatch | None:
        return self.incident_watches.get(watch_id)

    async def set_watch_enabled(
        self,
        watch_id: str,
        *,
        enabled: bool,
        updated_at: datetime,
    ) -> IncidentWatch | None:
        watch = self.incident_watches.get(watch_id)
        if watch is None:
            return None
        updated = replace(
            watch,
            enabled=enabled,
            updated_at=updated_at,
            next_refresh_at=updated_at if enabled else watch.next_refresh_at,
        )
        self.incident_watches[watch_id] = updated
        return updated

    async def delete_watch(self, watch_id: str) -> bool:
        if self.incident_watches.pop(watch_id, None) is None:
            return False
        observation_ids = {
            item.observation_id
            for item in self.watch_observations.values()
            if item.watch_id == watch_id
        }
        for observation_id in observation_ids:
            self.watch_observations.pop(observation_id, None)
        for change_id in tuple(self.watch_change_records):
            if self.watch_change_records[change_id].watch_id == watch_id:
                del self.watch_change_records[change_id]
        self.watch_latest_observation.pop(watch_id, None)
        self.watch_latest_successful_observation.pop(watch_id, None)
        return True

    async def due_watches(self, *, now: datetime) -> tuple[IncidentWatch, ...]:
        return tuple(
            sorted(
                (
                    item
                    for item in self.incident_watches.values()
                    if item.enabled and item.next_refresh_at <= now
                ),
                key=lambda item: (item.next_refresh_at, item.watch_id),
            )
        )

    async def latest_watch_observation(
        self, watch_id: str
    ) -> IncidentWatchObservation | None:
        observation_id = self.watch_latest_observation.get(watch_id)
        return self.watch_observations.get(observation_id) if observation_id else None

    async def latest_successful_watch_observation(
        self, watch_id: str
    ) -> IncidentWatchObservation | None:
        observation_id = self.watch_latest_successful_observation.get(watch_id)
        return self.watch_observations.get(observation_id) if observation_id else None

    async def record_watch_refresh(
        self,
        observation: IncidentWatchObservation,
        changes: tuple[IncidentWatchChange, ...],
    ) -> int:
        watch = self.incident_watches.get(observation.watch_id)
        if watch is None:
            raise ValueError("Incident watch does not exist.")
        existing_observation = self.watch_observations.get(observation.observation_id)
        if (
            existing_observation is not None
            and existing_observation.state_hash != observation.state_hash
        ):
            raise RuntimeError("Watch observation identity changed after persistence.")
        if existing_observation is None:
            self.watch_observations[observation.observation_id] = observation
        self.watch_latest_observation[watch.watch_id] = observation.observation_id
        if observation.successful:
            self.watch_latest_successful_observation[watch.watch_id] = (
                observation.observation_id
            )
        inserted = 0
        for change in changes:
            if change.watch_id != watch.watch_id:
                raise ValueError("Watch change belongs to a different watch.")
            existing_change = self.watch_change_records.get(change.change_id)
            if existing_change is None:
                self.watch_change_records[change.change_id] = change
                inserted += 1
            elif existing_change != change:
                raise RuntimeError("Watch change identity changed after persistence.")
        self.incident_watches[watch.watch_id] = replace(
            watch,
            updated_at=observation.observed_at,
            last_checked_at=observation.observed_at,
            next_refresh_at=observation.observed_at
            + timedelta(seconds=watch.refresh_interval_seconds),
            coverage_state=observation.coverage_state,
            unread_change_count=watch.unread_change_count + inserted,
        )
        return inserted

    async def watch_changes(
        self, watch_id: str, *, limit: int = 100
    ) -> tuple[IncidentWatchChange, ...]:
        if limit < 1 or limit > 500:
            raise ValueError("Watch timeline limit must be between 1 and 500.")
        return tuple(
            sorted(
                (
                    item
                    for item in self.watch_change_records.values()
                    if item.watch_id == watch_id
                ),
                key=lambda item: (item.created_at, item.change_id),
                reverse=True,
            )[:limit]
        )

    async def mark_watch_changes_read(
        self,
        watch_id: str,
        change_ids: tuple[str, ...],
        *,
        read_at: datetime,
    ) -> int:
        watch = self.incident_watches.get(watch_id)
        if watch is None:
            return 0
        selected_ids = set(change_ids)
        marked = 0
        for change_id, change in tuple(self.watch_change_records.items()):
            if (
                change.watch_id == watch_id
                and change.read_at is None
                and (not selected_ids or change_id in selected_ids)
            ):
                self.watch_change_records[change_id] = change.mark_read(read_at)
                marked += 1
        self.incident_watches[watch_id] = replace(
            watch,
            unread_change_count=max(0, watch.unread_change_count - marked),
        )
        return marked
