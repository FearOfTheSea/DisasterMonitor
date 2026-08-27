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
