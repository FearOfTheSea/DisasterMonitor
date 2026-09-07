"""Read-only transcript queries, independent of HTTP and storage mutations."""

from disaster_monitor.application.ports.conversation_store import ConversationReader
from disaster_monitor.domain.conversation import Conversation, ConversationSummary
from disaster_monitor.domain.errors import (
    ConversationNotFoundError as ConversationNotFoundError,
)


class ConversationQueries:
    def __init__(self, reader: ConversationReader) -> None:
        self._reader = reader

    async def list(self) -> tuple[ConversationSummary, ...]:
        return await self._reader.list()

    async def get(self, conversation_id: str) -> Conversation:
        conversation = await self._reader.get(conversation_id)
        if conversation is None:
            raise ConversationNotFoundError(conversation_id)
        return conversation
