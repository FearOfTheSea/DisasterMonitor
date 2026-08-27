"""Application port for atomic deletion of conversation-owned state."""

from typing import Protocol


class ConversationDeletionStore(Protocol):
    """Delete a transcript and all conversation-derived state atomically."""

    async def delete(self, conversation_id: str) -> bool: ...
