from datetime import UTC, datetime
from uuid import uuid4

import psycopg
import pytest

from disaster_monitor.domain.conversation import (
    AssistantMessagePayload,
    Conversation,
    ConversationMessage,
    ConversationRole,
)
from disaster_monitor.infrastructure.conversations.postgres_repository import (
    PostgresConversationRepository,
)
from disaster_monitor.infrastructure.operations.postgres_repository import (
    PostgresOperationalRepository,
)


@pytest.mark.asyncio
@pytest.mark.postgres
async def test_postgres_conversation_repository_persists_orders_and_cascades(
    postgres_dsn: str,
) -> None:
    dsn = postgres_dsn
    await PostgresOperationalRepository(dsn).migrate()
    async with await psycopg.AsyncConnection.connect(dsn) as connection:
        async with connection.cursor() as cursor:
            await cursor.execute("SELECT to_regclass('agent_memory')")
            assert (await cursor.fetchone())[0] == "agent_memory"
    conversation_id = f"test-conversation:{uuid4()}"
    second_id = f"test-conversation:{uuid4()}"
    timestamp = datetime(2026, 8, 21, 10, 0, tzinfo=UTC)
    repository = PostgresConversationRepository(dsn)
    await repository.create(Conversation(conversation_id, timestamp, timestamp))
    await repository.append(
        ConversationMessage(
            f"test-message:{uuid4()}",
            conversation_id,
            ConversationRole.USER,
            "First question",
            timestamp,
        )
    )
    await repository.append(
        ConversationMessage(
            f"test-message:{uuid4()}",
            conversation_id,
            ConversationRole.ASSISTANT,
            "First answer",
            timestamp,
            assistant_payload=AssistantMessagePayload(
                "assistant-answer.v1",
                {
                    "message": "First answer",
                    "media_gallery": {
                        "event_id": "event-1",
                        "items": [],
                        "warnings": ["No usable source photos were found."],
                    },
                },
            ),
        )
    )
    await repository.create(
        Conversation(second_id, timestamp, timestamp.replace(second=1))
    )

    try:
        reopened = PostgresConversationRepository(dsn)
        loaded = await reopened.get(conversation_id)
        listed = [
            item
            for item in await reopened.list()
            if item.conversation_id in {conversation_id, second_id}
        ]

        assert loaded is not None
        assert [message.content for message in loaded.messages] == [
            "First question",
            "First answer",
        ]
        assert loaded.messages[0].assistant_payload is None
        assert loaded.messages[1].assistant_payload is not None
        assert loaded.messages[1].assistant_payload.data["media_gallery"] == {
            "event_id": "event-1",
            "items": [],
            "warnings": ["No usable source photos were found."],
        }
        assert listed[0].conversation_id == second_id
        assert listed[1].preview == "First question"

        assert await reopened.delete(conversation_id) is True
        assert await reopened.get(conversation_id) is None
        async with await psycopg.AsyncConnection.connect(dsn) as connection:
            async with connection.cursor() as cursor:
                await cursor.execute(
                    "SELECT COUNT(*) FROM conversation_message "
                    "WHERE conversation_id=%s",
                    (conversation_id,),
                )
                assert (await cursor.fetchone())[0] == 0
    finally:
        await repository.delete(conversation_id)
        await repository.delete(second_id)
