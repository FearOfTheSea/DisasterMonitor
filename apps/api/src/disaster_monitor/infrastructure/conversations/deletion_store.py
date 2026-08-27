"""Persistence-specific atomic deletion of conversation-owned state."""

from disaster_monitor.infrastructure.conversations.memory_repository import (
    InMemoryConversationRepository,
)
from disaster_monitor.infrastructure.conversations.postgres_repository import (
    PostgresConversationRepository,
)
from disaster_monitor.infrastructure.memory.memory_repository import (
    InMemoryMemoryRepository,
)
from disaster_monitor.infrastructure.memory.postgres_repository import (
    PostgresMemoryRepository,
)


class InMemoryConversationDeletionStore:
    def __init__(
        self,
        conversations: InMemoryConversationRepository,
        memories: InMemoryMemoryRepository,
    ) -> None:
        self._conversations = conversations
        self._memories = memories

    async def delete(self, conversation_id: str) -> bool:
        delete_conversation = self._conversations.prepare_delete(conversation_id)
        if delete_conversation is None:
            return False
        delete_memories = self._memories.prepare_delete_for_conversation(
            conversation_id
        )
        delete_memories()
        delete_conversation()
        return True


class PostgresConversationDeletionStore:
    """Delete through the conversation FK root in one database transaction."""

    def __init__(
        self,
        conversations: PostgresConversationRepository,
        memories: PostgresMemoryRepository,
    ) -> None:
        if not conversations.shares_database_with(memories):
            raise ValueError(
                "Repositories do not share an atomic conversation deletion boundary."
            )
        self._conversations = conversations

    async def delete(self, conversation_id: str) -> bool:
        return await self._conversations.delete(conversation_id)
