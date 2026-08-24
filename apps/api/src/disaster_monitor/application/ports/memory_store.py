"""Application port for separate typed historical-memory persistence."""

from datetime import datetime
from typing import Protocol

from disaster_monitor.domain.memory import MemoryRecord


class MemoryStore(Protocol):
    async def save(
        self,
        record: MemoryRecord,
        *,
        superseded_memory_ids: tuple[str, ...] = (),
    ) -> None: ...

    async def get(self, memory_id: str) -> MemoryRecord | None: ...

    async def list_for_scope(
        self, conversation_id: str, physical_event_id: str | None = None
    ) -> tuple[MemoryRecord, ...]: ...

    async def mark_superseded(
        self,
        memory_id: str,
        *,
        superseded_by_memory_id: str,
    ) -> bool: ...

    async def mark_expired(self, memory_id: str) -> bool: ...

    async def mark_deleted_for_conversation(
        self, conversation_id: str, *, deleted_at: datetime
    ) -> int: ...
