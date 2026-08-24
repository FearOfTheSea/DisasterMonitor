"""Delete one conversation and all state owned by its lifecycle."""

from disaster_monitor.application.ports.conversation_deletion import (
    ConversationDeletionStore,
)
from disaster_monitor.domain.errors import ConversationNotFoundError


class DeleteConversation:
    """Execute deletion through one persistence-owned atomic boundary."""

    def __init__(self, store: ConversationDeletionStore) -> None:
        self._store = store

    async def execute(self, conversation_id: str) -> None:
        if not await self._store.delete(conversation_id):
            raise ConversationNotFoundError(conversation_id)
