from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from disaster_monitor.application.services.memory_recall import (
    MemoryRecallRequest,
    MemoryRecallService,
)
from disaster_monitor.domain.memory import (
    MemoryAuthority,
    MemoryLifecycleStatus,
    MemoryRecord,
    MemoryType,
)
from disaster_monitor.infrastructure.memory.memory_repository import (
    InMemoryMemoryRepository,
)

NOW = datetime(2026, 8, 24, 12, tzinfo=UTC)


def record(index: int, **changes) -> MemoryRecord:
    value = MemoryRecord(
        memory_id=f"memory:{index}",
        schema_version="agent-memory.v1",
        memory_type=MemoryType.PHYSICAL_EVENT_REFERENCE,
        status=MemoryLifecycleStatus.ACTIVE,
        summary=f"Historical reference {index}; current truth requires new evidence.",
        conversation_id="conversation-a",
        physical_event_id="physical-event:one",
        disaster_identifier="flood",
        country_code="TST",
        source_message_ids=(f"message:{index}",),
        evidence_ids=("physical-event:one",),
        world_state_version=f"state:{index}",
        created_at=NOW - timedelta(hours=index),
        confirmed_at=NOW - timedelta(hours=index),
        expires_at=NOW + timedelta(days=30),
    )
    return replace(value, **changes)


@pytest.mark.asyncio
async def test_recall_is_conversation_event_lifecycle_and_size_bounded() -> None:
    repository = InMemoryMemoryRepository()
    for index in range(8):
        await repository.save(record(index))
    await repository.save(
        record(20, conversation_id="conversation-b", memory_id="memory:other")
    )
    await repository.save(
        record(
            21,
            physical_event_id="physical-event:other",
            memory_id="memory:event-other",
        )
    )
    await repository.save(
        record(
            22,
            status=MemoryLifecycleStatus.EXPIRED,
            expires_at=NOW - timedelta(seconds=1),
            memory_id="memory:expired",
        )
    )
    await repository.save(
        record(
            25,
            expires_at=NOW - timedelta(seconds=1),
            memory_id="memory:stale-active",
        )
    )
    await repository.save(
        record(
            23,
            status=MemoryLifecycleStatus.SUPERSEDED,
            superseded_by_memory_id="memory:0",
            memory_id="memory:superseded",
        )
    )
    await repository.save(
        record(
            24,
            status=MemoryLifecycleStatus.DELETED,
            deleted_at=NOW,
            memory_id="memory:deleted",
        )
    )

    context = await MemoryRecallService(
        repository, maximum_records=5, maximum_characters=250
    ).recall(
        MemoryRecallRequest(
            conversation_id="conversation-a",
            physical_event_id="physical-event:one",
            disaster_identifier="flood",
            country_code="TST",
            now=NOW,
        )
    )

    assert len(context.records) <= 5
    assert context.total_characters <= 250
    assert all(item.conversation_id == "conversation-a" for item in context.records)
    assert all(
        item.physical_event_id == "physical-event:one" for item in context.records
    )
    assert {item.memory_id for item in context.records}.isdisjoint(
        {
            "memory:other",
            "memory:event-other",
            "memory:expired",
            "memory:superseded",
            "memory:deleted",
            "memory:stale-active",
        }
    )
    stale = await repository.get("memory:stale-active")
    assert stale is not None
    assert stale.status is MemoryLifecycleStatus.EXPIRED


@pytest.mark.asyncio
async def test_recalled_prior_state_is_read_only_history_not_current_evidence() -> None:
    repository = InMemoryMemoryRepository()
    await repository.save(record(1, world_state_version="state:prior"))

    context = await MemoryRecallService(repository).recall(
        MemoryRecallRequest(
            conversation_id="conversation-a",
            physical_event_id="physical-event:one",
            disaster_identifier="flood",
            country_code="TST",
            now=NOW,
        )
    )

    assert context.records[0].world_state_version == "state:prior"
    assert context.authority is MemoryAuthority.HISTORICAL_CONTEXT
    assert context.may_satisfy_current_evidence is False
    assert context.records[0].authority is MemoryAuthority.HISTORICAL_CONTEXT
    assert context.records[0].may_satisfy_current_evidence is False


@pytest.mark.asyncio
async def test_in_memory_save_replaces_the_active_physical_event_scope() -> None:
    repository = InMemoryMemoryRepository()
    first = record(1, world_state_version="state:prior")
    replacement = record(2, world_state_version="state:replacement")

    await repository.save(first)
    await repository.save(replacement)

    stored = await repository.list_for_scope(
        first.conversation_id, first.physical_event_id
    )
    active = tuple(
        item for item in stored if item.status is MemoryLifecycleStatus.ACTIVE
    )
    superseded = tuple(
        item for item in stored if item.status is MemoryLifecycleStatus.SUPERSEDED
    )

    assert active == (replacement,)
    assert len(superseded) == 1
    assert superseded[0].memory_id == first.memory_id
    assert superseded[0].superseded_by_memory_id == replacement.memory_id


@pytest.mark.asyncio
async def test_in_memory_repository_supports_deletion_and_recreation() -> None:
    repository = InMemoryMemoryRepository()
    await repository.save(record(1))

    assert await repository.get("memory:1") == record(1)
    assert (
        await repository.mark_deleted_for_conversation("conversation-a", deleted_at=NOW)
        == 1
    )
    recalled = await MemoryRecallService(repository).recall(
        MemoryRecallRequest(conversation_id="conversation-a", now=NOW)
    )

    assert recalled.records == ()
