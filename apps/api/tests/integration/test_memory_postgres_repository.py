import asyncio
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import psycopg
import pytest

from disaster_monitor.application.use_cases.delete_conversation import (
    DeleteConversation,
)
from disaster_monitor.domain.conversation import (
    Conversation,
    ConversationMessage,
    ConversationRole,
)
from disaster_monitor.domain.memory import (
    MemoryLifecycleStatus,
    MemoryRecord,
    MemoryType,
)
from disaster_monitor.infrastructure.conversations.postgres_repository import (
    PostgresConversationRepository,
)
from disaster_monitor.infrastructure.memory.postgres_repository import (
    PostgresMemoryRepository,
)
from disaster_monitor.infrastructure.operations.postgres_repository import (
    PostgresOperationalRepository,
)


def memory_record(
    *,
    memory_id: str,
    conversation_id: str,
    physical_event_id: str,
    world_state_version: str,
    confirmed_at: datetime,
) -> MemoryRecord:
    return MemoryRecord(
        memory_id=memory_id,
        schema_version="agent-memory.v1",
        memory_type=MemoryType.PHYSICAL_EVENT_REFERENCE,
        status=MemoryLifecycleStatus.ACTIVE,
        summary="Historical event reference; current truth requires new evidence.",
        conversation_id=conversation_id,
        physical_event_id=physical_event_id,
        disaster_identifier="flood",
        country_code="TST",
        source_message_ids=(f"message:{memory_id}",),
        evidence_ids=(physical_event_id,),
        world_state_version=world_state_version,
        created_at=confirmed_at,
        confirmed_at=confirmed_at,
        expires_at=confirmed_at + timedelta(days=30),
    )


@pytest.mark.asyncio
@pytest.mark.postgres
async def test_postgres_memory_survives_recreation_and_conversation_deletion(
    postgres_dsn: str,
) -> None:
    dsn = postgres_dsn
    await PostgresOperationalRepository(dsn).migrate()
    conversation_id = f"test-memory-conversation:{uuid4()}"
    now = datetime(2026, 8, 24, 12, tzinfo=UTC)
    conversations = PostgresConversationRepository(dsn)
    await conversations.create(Conversation(conversation_id, now, now))
    await conversations.append(
        ConversationMessage(
            f"test-memory-message:{uuid4()}",
            conversation_id,
            ConversationRole.USER,
            "Persist this transcript with its derived memory.",
            now,
        )
    )
    memory_id = f"memory:{uuid4()}"
    record = MemoryRecord(
        memory_id=memory_id,
        schema_version="agent-memory.v1",
        memory_type=MemoryType.PHYSICAL_EVENT_REFERENCE,
        status=MemoryLifecycleStatus.ACTIVE,
        summary="Historical event reference; current truth requires new evidence.",
        conversation_id=conversation_id,
        physical_event_id="physical-event:test",
        disaster_identifier="flood",
        country_code="TST",
        source_message_ids=("message:user", "message:assistant"),
        evidence_ids=("physical-event:test",),
        world_state_version="state:test",
        created_at=now,
        confirmed_at=now,
        expires_at=now + timedelta(days=30),
    )

    try:
        await PostgresMemoryRepository(dsn).save(record)

        reopened = PostgresMemoryRepository(dsn)
        assert await reopened.get(memory_id) == record
        assert await reopened.list_for_scope(
            conversation_id, "physical-event:test"
        ) == (record,)

        await DeleteConversation(conversations).execute(conversation_id)
        assert await conversations.get(conversation_id) is None
        async with await psycopg.AsyncConnection.connect(dsn) as connection:
            async with connection.cursor() as cursor:
                await cursor.execute(
                    "SELECT COUNT(*) FROM conversation_message "
                    "WHERE conversation_id=%s",
                    (conversation_id,),
                )
                assert (await cursor.fetchone())[0] == 0
                await cursor.execute(
                    "SELECT COUNT(*) FROM agent_memory WHERE conversation_id=%s",
                    (conversation_id,),
                )
                assert (await cursor.fetchone())[0] == 0
    finally:
        await conversations.delete(conversation_id)


@pytest.mark.asyncio
@pytest.mark.postgres
async def test_concurrent_memory_saves_leave_one_active_world_state_per_event_scope(
    postgres_dsn: str,
) -> None:
    dsn = postgres_dsn
    await PostgresOperationalRepository(dsn).migrate()
    conversation_id = f"test-memory-concurrency:{uuid4()}"
    physical_event_id = f"physical-event:{uuid4()}"
    now = datetime(2026, 8, 24, 12, tzinfo=UTC)
    conversations = PostgresConversationRepository(dsn)
    repository = PostgresMemoryRepository(dsn)
    await conversations.create(Conversation(conversation_id, now, now))
    records = (
        memory_record(
            memory_id=f"memory:{uuid4()}",
            conversation_id=conversation_id,
            physical_event_id=physical_event_id,
            world_state_version="state:concurrent-a",
            confirmed_at=now,
        ),
        memory_record(
            memory_id=f"memory:{uuid4()}",
            conversation_id=conversation_id,
            physical_event_id=physical_event_id,
            world_state_version="state:concurrent-b",
            confirmed_at=now + timedelta(seconds=1),
        ),
    )

    try:
        await asyncio.gather(*(repository.save(record) for record in records))

        stored = await repository.list_for_scope(conversation_id, physical_event_id)
        active = tuple(
            record for record in stored if record.status is MemoryLifecycleStatus.ACTIVE
        )
        superseded = tuple(
            record
            for record in stored
            if record.status is MemoryLifecycleStatus.SUPERSEDED
        )

        assert len(active) == 1
        assert len(superseded) == 1
        assert superseded[0].superseded_by_memory_id == active[0].memory_id
        assert {record.world_state_version for record in stored} == {
            "state:concurrent-a",
            "state:concurrent-b",
        }
        async with await psycopg.AsyncConnection.connect(dsn) as connection:
            with pytest.raises(psycopg.errors.UniqueViolation):
                async with connection.transaction():
                    async with connection.cursor() as cursor:
                        await cursor.execute(
                            """
                            UPDATE agent_memory
                            SET lifecycle_status='active',
                                superseded_by_memory_id=NULL
                            WHERE memory_id=%s
                            """,
                            (superseded[0].memory_id,),
                        )
    finally:
        await conversations.delete(conversation_id)
