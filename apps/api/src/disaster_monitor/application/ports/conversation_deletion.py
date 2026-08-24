"""Application port for atomic deletion of conversation-owned state."""

from typing import Protocol


class ConversationDeletionStore(Protocol):
    async def delete(self, conversation_id: str) -> bool: ...
