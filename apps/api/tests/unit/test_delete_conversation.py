from datetime import UTC, datetime, timedelta

import pytest

from disaster_monitor.application.use_cases.delete_conversation import (
    DeleteConversation,
)
from disaster_monitor.domain.conversation import Conversation
from disaster_monitor.domain.errors import ConversationNotFoundError
from disaster_monitor.domain.memory import (
    MemoryLifecycleStatus,
    MemoryRecord,
    MemoryType,
)
from disaster_monitor.infrastructure.conversations.deletion_store import (
    InMemoryConversationDeletionStore,
)
from disaster_monitor.infrastructure.conversations.memory_repository import (
    InMemoryConversationRepository,
)
from disaster_monitor.infrastructure.memory.memory_repository import (
    InMemoryMemoryRepository,
)

NOW = datetime(2026, 8, 24, 12, tzinfo=UTC)


def memory_record(conversation_id: str) -> MemoryRecord:
    return MemoryRecord(
        memory_id="memory:test",
        schema_version="agent-memory.v1",
        memory_type=MemoryType.PHYSICAL_EVENT_REFERENCE,
        status=MemoryLifecycleStatus.ACTIVE,
        summary="Historical event reference; current truth requires new evidence.",
        conversation_id=conversation_id,
        physical_event_id="physical-event:test",
        disaster_identifier="flood",
        country_code="TST",
        source_message_ids=("message:user", "message:assistant"),
        evidence_ids=("physical-event:test",),
        world_state_version="state:test",
        created_at=NOW,
        confirmed_at=NOW,
        expires_at=NOW + timedelta(days=30),
    )


@pytest.mark.asyncio
async def test_in_memory_conversation_deletion_physically_removes_derived_memory() -> (
    None
):
    conversations = InMemoryConversationRepository()
    memories = InMemoryMemoryRepository()
    await conversations.create(Conversation("conversation-a", NOW, NOW))
    await memories.save(memory_record("conversation-a"))
    use_case = DeleteConversation(
        InMemoryConversationDeletionStore(conversations, memories)
    )

    await use_case.execute("conversation-a")

    assert await conversations.get("conversation-a") is None
    assert await memories.list_for_scope("conversation-a") == ()


@pytest.mark.asyncio
async def test_deletion_failure_cannot_partially_mutate_conversation_or_memory() -> (
    None
):
    conversation = Conversation("conversation-a", NOW, NOW)
    memory = memory_record("conversation-a")
    durable_state = {"conversation": conversation, "memory": memory}

    class FailingAtomicDeletionStore:
        async def delete(self, conversation_id: str) -> bool:
            assert conversation_id == "conversation-a"
            raise RuntimeError("simulated transaction failure")

    with pytest.raises(RuntimeError, match="simulated transaction failure"):
        await DeleteConversation(FailingAtomicDeletionStore()).execute("conversation-a")

    assert durable_state == {"conversation": conversation, "memory": memory}


@pytest.mark.asyncio
async def test_missing_conversation_is_reported_by_application_use_case() -> None:
    class MissingDeletionStore:
        async def delete(self, conversation_id: str) -> bool:
            return False

    with pytest.raises(ConversationNotFoundError):
        await DeleteConversation(MissingDeletionStore()).execute("missing")
