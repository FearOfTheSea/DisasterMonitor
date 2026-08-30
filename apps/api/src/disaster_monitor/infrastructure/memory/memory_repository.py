"""In-memory typed memory repository for tests and no-database development."""

from collections.abc import Callable
from dataclasses import replace
from datetime import datetime

from disaster_monitor.domain.memory import (
    MemoryLifecycleStatus,
    MemoryRecord,
    MemoryType,
)


class InMemoryMemoryRepository:
    def __init__(self) -> None:
        self._records: dict[str, MemoryRecord] = {}

    async def save(
        self,
        record: MemoryRecord,
        *,
        superseded_memory_ids: tuple[str, ...] = (),
    ) -> None:
        if (
            record.status is MemoryLifecycleStatus.ACTIVE
            and record.memory_type is MemoryType.PHYSICAL_EVENT_REFERENCE
            and record.physical_event_id is not None
        ):
            for memory_id, scoped_record in tuple(self._records.items()):
                if (
                    memory_id != record.memory_id
                    and scoped_record.status is MemoryLifecycleStatus.ACTIVE
                    and scoped_record.memory_type is record.memory_type
                    and scoped_record.conversation_id == record.conversation_id
                    and scoped_record.physical_event_id == record.physical_event_id
                ):
                    self._records[memory_id] = replace(
                        scoped_record,
                        status=MemoryLifecycleStatus.SUPERSEDED,
                        superseded_by_memory_id=record.memory_id,
                    )
            self._records[record.memory_id] = record
            return
        self._records[record.memory_id] = record
        for memory_id in superseded_memory_ids:
            existing = self._records.get(memory_id)
            if existing is not None and existing.status is MemoryLifecycleStatus.ACTIVE:
                self._records[memory_id] = replace(
                    existing,
                    status=MemoryLifecycleStatus.SUPERSEDED,
                    superseded_by_memory_id=record.memory_id,
                )

    async def get(self, memory_id: str) -> MemoryRecord | None:
        return self._records.get(memory_id)

    async def list_for_scope(
        self, conversation_id: str, physical_event_id: str | None = None
    ) -> tuple[MemoryRecord, ...]:
        return tuple(
            sorted(
                (
                    record
                    for record in self._records.values()
                    if record.conversation_id == conversation_id
                    and (
                        physical_event_id is None
                        or record.physical_event_id == physical_event_id
                    )
                ),
                key=lambda item: (item.confirmed_at, item.memory_id),
                reverse=True,
            )
        )

    async def mark_superseded(
        self,
        memory_id: str,
        *,
        superseded_by_memory_id: str,
    ) -> bool:
        record = self._records.get(memory_id)
        if record is None or record.status is not MemoryLifecycleStatus.ACTIVE:
            return False
        self._records[memory_id] = replace(
            record,
            status=MemoryLifecycleStatus.SUPERSEDED,
            superseded_by_memory_id=superseded_by_memory_id,
        )
        return True

    async def mark_expired(self, memory_id: str) -> bool:
        record = self._records.get(memory_id)
        if (
            record is None
            or record.status is not MemoryLifecycleStatus.ACTIVE
            or record.expires_at is None
        ):
            return False
        self._records[memory_id] = replace(record, status=MemoryLifecycleStatus.EXPIRED)
        return True

    async def mark_deleted_for_conversation(
        self, conversation_id: str, *, deleted_at: datetime
    ) -> int:
        count = 0
        for memory_id, record in tuple(self._records.items()):
            if (
                record.conversation_id != conversation_id
                or record.status is MemoryLifecycleStatus.DELETED
            ):
                continue
            self._records[memory_id] = replace(
                record,
                status=MemoryLifecycleStatus.DELETED,
                superseded_by_memory_id=None,
                deleted_at=deleted_at,
            )
            count += 1
        return count

    def prepare_delete_for_conversation(
        self, conversation_id: str
    ) -> Callable[[], None]:
        """Prepare physical removal for a coordinated conversation deletion."""
        records = {
            memory_id: record
            for memory_id, record in self._records.items()
            if record.conversation_id != conversation_id
        }

        def commit() -> None:
            self._records = records

        return commit
