"""In-memory conversation repository for tests and no-database development."""

from collections.abc import Callable
from dataclasses import replace
from datetime import timedelta

from disaster_monitor.domain.conversation import (
    Conversation,
    ConversationMessage,
    ConversationSummary,
    conversation_preview,
)
from disaster_monitor.domain.errors import ConversationNotFoundError


class InMemoryConversationRepository:
    def __init__(self) -> None:
        self._conversations: dict[str, Conversation] = {}
        self._messages: dict[str, ConversationMessage] = {}

    async def create(self, conversation: Conversation) -> None:
        if conversation.conversation_id in self._conversations:
            raise ValueError("Conversation ID already exists.")
        self._conversations[conversation.conversation_id] = conversation

    async def get(self, conversation_id: str) -> Conversation | None:
        conversation = self._conversations.get(conversation_id)
        if conversation is None:
            return None
        messages = tuple(
            sorted(
                (
                    message
                    for message in self._messages.values()
                    if message.conversation_id == conversation_id
                ),
                key=lambda message: (message.created_at, message.message_id),
            )
        )
        return Conversation(
            conversation_id=conversation.conversation_id,
            created_at=conversation.created_at,
            updated_at=conversation.updated_at,
            messages=messages,
        )

    async def list(self) -> tuple[ConversationSummary, ...]:
        summaries = []
        for conversation in self._conversations.values():
            loaded = await self.get(conversation.conversation_id)
            assert loaded is not None
            summaries.append(
                ConversationSummary(
                    conversation_id=loaded.conversation_id,
                    created_at=loaded.created_at,
                    updated_at=loaded.updated_at,
                    preview=conversation_preview(loaded.messages),
                )
            )
        return tuple(
            sorted(
                summaries,
                key=lambda item: (item.updated_at, item.conversation_id),
                reverse=True,
            )
        )

    async def append(self, message: ConversationMessage) -> None:
        conversation = self._conversations.get(message.conversation_id)
        if conversation is None:
            raise ConversationNotFoundError(message.conversation_id)
        if message.message_id in self._messages:
            raise ValueError("Message ID already exists.")
        created_at = max(
            message.created_at,
            conversation.updated_at + timedelta(microseconds=1),
        )
        stored_message = replace(message, created_at=created_at)
        self._messages[message.message_id] = stored_message
        self._conversations[message.conversation_id] = Conversation(
            conversation_id=conversation.conversation_id,
            created_at=conversation.created_at,
            updated_at=created_at,
            messages=conversation.messages,
        )

    async def delete(self, conversation_id: str) -> bool:
        deletion = self.prepare_delete(conversation_id)
        if deletion is None:
            return False
        deletion()
        return True

    def prepare_delete(self, conversation_id: str) -> Callable[[], None] | None:
        """Prepare a non-failing state replacement for coordinated deletion."""
        if conversation_id not in self._conversations:
            return None
        conversations = {
            stored_id: conversation
            for stored_id, conversation in self._conversations.items()
            if stored_id != conversation_id
        }
        messages = {
            message_id: message
            for message_id, message in self._messages.items()
            if message.conversation_id != conversation_id
        }

        def commit() -> None:
            self._conversations = conversations
            self._messages = messages

        return commit
