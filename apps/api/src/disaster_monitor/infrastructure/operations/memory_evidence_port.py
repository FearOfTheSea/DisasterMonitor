"""Deterministic in-memory operational repository for tests and safe fallback."""

from dataclasses import replace
from datetime import datetime

from disaster_monitor.application.ports.incident_projection import (
    IncidentProjectionRecord,
)
from disaster_monitor.domain.operations import (
    AuditEventRecord,
    EventObservationLinkRecord,
    NormalizedObservationRecord,
    OperatorActionRecord,
    PhysicalEventRecord,
    SourceSnapshotRecord,
    WorldStateVersionRecord,
)
from disaster_monitor.infrastructure.operations.memory_state import MemoryState


class EvidenceMemoryPort(MemoryState):
    async def append_snapshot(self, snapshot: SourceSnapshotRecord) -> bool:
        existing_id = self.snapshot_idempotency.get(snapshot.idempotency_key)
        if existing_id is not None:
            return False
        if snapshot.snapshot_id in self.snapshot_records:
            raise RuntimeError("Snapshot ID maps to different idempotency identity.")
        self.snapshot_records[snapshot.snapshot_id] = snapshot
        self.snapshot_idempotency[snapshot.idempotency_key] = snapshot.snapshot_id
        return True

    async def append_incident_projection(
        self, projection: IncidentProjectionRecord
    ) -> bool:
        existing = self.incident_projections.get(projection.projection_id)
        if existing is not None:
            if existing != projection:
                raise RuntimeError("Incident projection identity was reused.")
            return False
        self.incident_projections[projection.projection_id] = projection
        return True

    async def latest_incident_projection(
        self,
    ) -> IncidentProjectionRecord | None:
        return max(
            self.incident_projections.values(),
            key=lambda item: (item.retrieved_at, item.projection_id),
            default=None,
        )

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
            if replace(event, created_at=existing.created_at) != existing:
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
