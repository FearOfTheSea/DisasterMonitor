"""PostgreSQL adapter for durable assistant conversations."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, cast

import psycopg
from psycopg.rows import dict_row

from disaster_monitor.domain.conversation import (
    Conversation,
    ConversationMessage,
    ConversationRole,
    ConversationSummary,
)
from disaster_monitor.domain.errors import ConversationNotFoundError


class PostgresConversationRepository:
    def __init__(self, dsn: str) -> None:
        if not dsn.strip():
            raise ValueError("PostgreSQL DSN must not be empty.")
        self._dsn = dsn

    async def create(self, conversation: Conversation) -> None:
        async with await self._connection() as connection:
            async with connection.cursor() as cursor:
                await cursor.execute(
                    """
                    INSERT INTO conversation(conversation_id, created_at, updated_at)
                    VALUES (%s, %s, %s)
                    """,
                    (
                        conversation.conversation_id,
                        conversation.created_at,
                        conversation.updated_at,
                    ),
                )

    async def get(self, conversation_id: str) -> Conversation | None:
        async with await self._connection() as connection:
            async with connection.cursor(row_factory=dict_row) as cursor:
                await cursor.execute(
                    """
                    SELECT conversation_id, created_at, updated_at
                    FROM conversation WHERE conversation_id=%s
                    """,
                    (conversation_id,),
                )
                row = await cursor.fetchone()
                if row is None:
                    return None
                await cursor.execute(
                    """
                    SELECT message_id, conversation_id, role, content, created_at
                    FROM conversation_message
                    WHERE conversation_id=%s
                    ORDER BY created_at, message_id
                    """,
                    (conversation_id,),
                )
                messages = tuple(_message(item) for item in await cursor.fetchall())
        return Conversation(
            conversation_id=str(row["conversation_id"]),
            created_at=cast(datetime, row["created_at"]),
            updated_at=cast(datetime, row["updated_at"]),
            messages=messages,
        )

    async def list(self) -> tuple[ConversationSummary, ...]:
        async with await self._connection() as connection:
            async with connection.cursor(row_factory=dict_row) as cursor:
                await cursor.execute(
                    """
                    SELECT
                        conversation_id, created_at, updated_at,
                        COALESCE((
                            SELECT content
                            FROM conversation_message AS message
                            WHERE message.conversation_id = conversation.conversation_id
                              AND message.role = 'user'
                            ORDER BY message.created_at, message.message_id
                            LIMIT 1
                        ), '') AS preview
                    FROM conversation
                    ORDER BY updated_at DESC, conversation_id DESC
                    """
                )
                rows = await cursor.fetchall()
        return tuple(
            ConversationSummary(
                conversation_id=str(row["conversation_id"]),
                created_at=cast(datetime, row["created_at"]),
                updated_at=cast(datetime, row["updated_at"]),
                preview=str(row["preview"])[:120],
            )
            for row in rows
        )

    async def append(self, message: ConversationMessage) -> None:
        async with await self._connection() as connection:
            async with connection.cursor() as cursor:
                await cursor.execute(
                    """
                    SELECT updated_at FROM conversation
                    WHERE conversation_id=%s
                    FOR UPDATE
                    """,
                    (message.conversation_id,),
                )
                row = await cursor.fetchone()
                if row is None:
                    raise ConversationNotFoundError(message.conversation_id)
                created_at = max(
                    message.created_at,
                    cast(datetime, row[0]) + timedelta(microseconds=1),
                )
                await cursor.execute(
                    """
                    INSERT INTO conversation_message(
                        message_id, conversation_id, role, content, created_at
                    ) VALUES (%s, %s, %s, %s, %s)
                    """,
                    (
                        message.message_id,
                        message.conversation_id,
                        message.role.value,
                        message.content,
                        created_at,
                    ),
                )
                await cursor.execute(
                    """
                    UPDATE conversation SET updated_at=%s
                    WHERE conversation_id=%s
                    """,
                    (created_at, message.conversation_id),
                )

    async def delete(self, conversation_id: str) -> bool:
        async with await self._connection() as connection:
            async with connection.cursor() as cursor:
                await cursor.execute(
                    "DELETE FROM conversation WHERE conversation_id=%s",
                    (conversation_id,),
                )
                return cursor.rowcount == 1

    async def _connection(self) -> psycopg.AsyncConnection[Any]:
        return await psycopg.AsyncConnection.connect(self._dsn)


def _message(row: dict[str, Any]) -> ConversationMessage:
    return ConversationMessage(
        message_id=str(row["message_id"]),
        conversation_id=str(row["conversation_id"]),
        role=ConversationRole(str(row["role"])),
        content=str(row["content"]),
        created_at=cast(datetime, row["created_at"]),
    )
