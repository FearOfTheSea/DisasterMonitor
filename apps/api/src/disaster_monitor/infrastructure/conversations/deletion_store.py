"""Atomic in-memory deletion of a conversation and its derived memory."""

from disaster_monitor.infrastructure.conversations.memory_repository import (
    InMemoryConversationRepository,
)
from disaster_monitor.infrastructure.memory.memory_repository import (
    InMemoryMemoryRepository,
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
        if conversation_id not in self._conversations.conversations:
            return False
        conversations = {
            key: value
            for key, value in self._conversations.conversations.items()
            if key != conversation_id
        }
        messages = {
            key: value
            for key, value in self._conversations.messages.items()
            if value.conversation_id != conversation_id
        }
        memories = {
            key: value
            for key, value in self._memories.records.items()
            if value.conversation_id != conversation_id
        }
        self._conversations.conversations = conversations
        self._conversations.messages = messages
        self._memories.records = memories
        return True
