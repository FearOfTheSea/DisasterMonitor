"""In-memory conversation repository for tests and no-database development."""

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
        self.conversations: dict[str, Conversation] = {}
        self.messages: dict[str, ConversationMessage] = {}

    async def create(self, conversation: Conversation) -> None:
        if conversation.conversation_id in self.conversations:
            raise ValueError("Conversation ID already exists.")
        self.conversations[conversation.conversation_id] = conversation

    async def get(self, conversation_id: str) -> Conversation | None:
        conversation = self.conversations.get(conversation_id)
        if conversation is None:
            return None
        messages = tuple(
            sorted(
                (
                    message
                    for message in self.messages.values()
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
        for conversation in self.conversations.values():
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
        conversation = self.conversations.get(message.conversation_id)
        if conversation is None:
            raise ConversationNotFoundError(message.conversation_id)
        if message.message_id in self.messages:
            raise ValueError("Message ID already exists.")
        created_at = max(
            message.created_at,
            conversation.updated_at + timedelta(microseconds=1),
        )
        stored_message = replace(message, created_at=created_at)
        self.messages[message.message_id] = stored_message
        self.conversations[message.conversation_id] = Conversation(
            conversation_id=conversation.conversation_id,
            created_at=conversation.created_at,
            updated_at=created_at,
            messages=conversation.messages,
        )

    async def delete(self, conversation_id: str) -> bool:
        if conversation_id not in self.conversations:
            return False
        del self.conversations[conversation_id]
        self.messages = {
            message_id: message
            for message_id, message in self.messages.items()
            if message.conversation_id != conversation_id
        }
        return True
