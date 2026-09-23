"""Deterministic in-memory operational repository for tests and safe fallback."""

from dataclasses import replace
from datetime import datetime, timedelta

from disaster_monitor.domain.disaster import (
    IncidentWatch,
    IncidentWatchChange,
    IncidentWatchObservation,
)
from disaster_monitor.infrastructure.operations.memory_state import MemoryState


class WatchMemoryPort(MemoryState):
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
