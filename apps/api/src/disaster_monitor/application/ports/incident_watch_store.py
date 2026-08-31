"""Persistence contract for durable local incident watches."""

from datetime import datetime
from typing import Protocol

from disaster_monitor.domain.disaster import (
    IncidentWatch,
    IncidentWatchChange,
    IncidentWatchObservation,
)


class IncidentWatchStore(Protocol):
    async def create_watch(self, watch: IncidentWatch) -> bool: ...

    async def list_watches(self) -> tuple[IncidentWatch, ...]: ...

    async def get_watch(self, watch_id: str) -> IncidentWatch | None: ...

    async def set_watch_enabled(
        self,
        watch_id: str,
        *,
        enabled: bool,
        updated_at: datetime,
    ) -> IncidentWatch | None: ...

    async def delete_watch(self, watch_id: str) -> bool: ...

    async def due_watches(self, *, now: datetime) -> tuple[IncidentWatch, ...]: ...

    async def latest_watch_observation(
        self, watch_id: str
    ) -> IncidentWatchObservation | None: ...

    async def latest_successful_watch_observation(
        self, watch_id: str
    ) -> IncidentWatchObservation | None: ...

    async def record_watch_refresh(
        self,
        observation: IncidentWatchObservation,
        changes: tuple[IncidentWatchChange, ...],
    ) -> int: ...

    async def watch_changes(
        self, watch_id: str, *, limit: int = 100
    ) -> tuple[IncidentWatchChange, ...]: ...

    async def mark_watch_changes_read(
        self,
        watch_id: str,
        change_ids: tuple[str, ...],
        *,
        read_at: datetime,
    ) -> int: ...
