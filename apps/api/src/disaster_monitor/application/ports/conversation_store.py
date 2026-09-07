"""Application port for durable assistant transcript storage."""

from typing import Protocol

from disaster_monitor.domain.conversation import (
    Conversation,
    ConversationMessage,
    ConversationSummary,
)


class ConversationReader(Protocol):
    async def get(self, conversation_id: str) -> Conversation | None: ...

    async def list(self) -> tuple[ConversationSummary, ...]: ...


class ConversationStore(ConversationReader, Protocol):
    async def create(self, conversation: Conversation) -> None: ...

    async def append(self, message: ConversationMessage) -> None: ...

    async def delete(self, conversation_id: str) -> bool: ...
