"""Bounded deterministic recall of non-authoritative historical references."""

from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256

from disaster_monitor.application.ports.memory_store import MemoryStore
from disaster_monitor.domain.memory import (
    MemoryAuthority,
    MemoryContextArtifact,
    MemoryContextItem,
    MemoryLifecycleStatus,
    MemoryRecord,
)

MAX_MEMORY_RECORDS = 5
MAX_MEMORY_CHARACTERS = 1_500


@dataclass(frozen=True, slots=True)
class MemoryRecallRequest:
    conversation_id: str
    now: datetime
    physical_event_id: str | None = None
    disaster_identifier: str | None = None
    country_code: str | None = None


class MemoryRecallService:
    def __init__(
        self,
        store: MemoryStore,
        *,
        maximum_records: int = MAX_MEMORY_RECORDS,
        maximum_characters: int = MAX_MEMORY_CHARACTERS,
    ) -> None:
        if not 1 <= maximum_records <= MAX_MEMORY_RECORDS:
            raise ValueError("Memory recall cannot exceed five records.")
        if maximum_characters < 1:
            raise ValueError("Memory recall character budget must be positive.")
        self._store = store
        self._maximum_records = maximum_records
        self._maximum_characters = maximum_characters

    async def recall(self, request: MemoryRecallRequest) -> MemoryContextArtifact:
        records = await self._store.list_for_scope(
            request.conversation_id, request.physical_event_id
        )
        for record in records:
            if (
                record.status is MemoryLifecycleStatus.ACTIVE
                and record.expires_at is not None
                and record.expires_at <= request.now
            ):
                await self._store.mark_expired(record.memory_id)
        eligible = sorted(
            (record for record in records if _eligible(record, request)),
            key=lambda item: (item.confirmed_at, item.created_at, item.memory_id),
            reverse=True,
        )
        selected: list[MemoryRecord] = []
        characters = 0
        for record in eligible:
            if len(selected) >= self._maximum_records:
                break
            size = len(record.summary)
            if size > self._maximum_characters:
                continue
            if characters + size > self._maximum_characters:
                continue
            selected.append(record)
            characters += size
        material = "|".join(
            (
                request.conversation_id,
                request.physical_event_id or "conversation",
                *(item.memory_id for item in selected),
            )
        )
        return MemoryContextArtifact(
            context_id=(
                f"memory-context:{sha256(material.encode('utf-8')).hexdigest()[:24]}"
            ),
            conversation_id=request.conversation_id,
            physical_event_id=request.physical_event_id,
            records=tuple(_context_item(item) for item in selected),
            created_at=request.now,
            total_characters=characters,
            maximum_records=self._maximum_records,
            maximum_characters=self._maximum_characters,
            authority=MemoryAuthority.HISTORICAL_CONTEXT,
            may_satisfy_current_evidence=False,
        )


def _eligible(record: MemoryRecord, request: MemoryRecallRequest) -> bool:
    if (
        record.conversation_id != request.conversation_id
        or record.status is not MemoryLifecycleStatus.ACTIVE
        or (record.expires_at is not None and record.expires_at <= request.now)
    ):
        return False
    if request.physical_event_id is not None and (
        record.physical_event_id != request.physical_event_id
    ):
        return False
    if request.disaster_identifier is not None and (
        record.disaster_identifier != request.disaster_identifier
    ):
        return False
    return request.country_code is None or record.country_code == request.country_code


def _context_item(record: MemoryRecord) -> MemoryContextItem:
    return MemoryContextItem(
        memory_id=record.memory_id,
        memory_type=record.memory_type,
        summary=record.summary,
        conversation_id=record.conversation_id,
        physical_event_id=record.physical_event_id,
        disaster_identifier=record.disaster_identifier,
        country_code=record.country_code,
        source_message_ids=record.source_message_ids,
        evidence_ids=record.evidence_ids,
        world_state_version=record.world_state_version,
        confirmed_at=record.confirmed_at,
    )
