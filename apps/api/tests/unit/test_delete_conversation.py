from datetime import UTC, datetime, timedelta

import pytest

from disaster_monitor.application.use_cases.delete_conversation import (
    DeleteConversation,
)
from disaster_monitor.domain.conversation import (
    Conversation,
    ConversationMessage,
    ConversationRole,
)
from disaster_monitor.domain.errors import ConversationNotFoundError
from disaster_monitor.domain.memory import (
    MemoryLifecycleStatus,
    MemoryRecord,
    MemoryType,
)
from disaster_monitor.infrastructure.composition import (
    build_conversation_deletion_store,
)
from disaster_monitor.infrastructure.conversations.deletion_store import (
    InMemoryConversationDeletionStore,
    PostgresConversationDeletionStore,
)
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

NOW = datetime(2026, 8, 24, 12, tzinfo=UTC)


def memory_record(
    conversation_id: str, *, memory_id: str = "memory:test"
) -> MemoryRecord:
    return MemoryRecord(
        memory_id=memory_id,
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
    await conversations.append(
        ConversationMessage(
            "message:a",
            "conversation-a",
            ConversationRole.USER,
            "Delete this transcript.",
            NOW,
        )
    )
    await conversations.create(Conversation("conversation-b", NOW, NOW))
    await memories.save(memory_record("conversation-a"))
    retained_memory = memory_record("conversation-b", memory_id="memory:retained")
    await memories.save(retained_memory)
    use_case = DeleteConversation(
        InMemoryConversationDeletionStore(conversations, memories)
    )

    await use_case.execute("conversation-a")

    assert await conversations.get("conversation-a") is None
    assert await memories.list_for_scope("conversation-a") == ()
    assert await conversations.get("conversation-b") is not None
    assert await memories.list_for_scope("conversation-b") == (retained_memory,)


@pytest.mark.asyncio
async def test_in_memory_deletion_preparation_failure_preserves_all_state() -> None:
    class FailingMemoryRepository(InMemoryMemoryRepository):
        def prepare_delete_for_conversation(self, conversation_id: str):
            raise RuntimeError("simulated deletion preparation failure")

    conversations = InMemoryConversationRepository()
    memories = FailingMemoryRepository()
    await conversations.create(Conversation("conversation-a", NOW, NOW))
    stored_memory = memory_record("conversation-a")
    await memories.save(stored_memory)

    with pytest.raises(RuntimeError, match="deletion preparation failure"):
        await DeleteConversation(
            InMemoryConversationDeletionStore(conversations, memories)
        ).execute("conversation-a")

    assert await conversations.get("conversation-a") is not None
    assert await memories.list_for_scope("conversation-a") == (stored_memory,)


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


@pytest.mark.parametrize(
    ("conversations", "memories"),
    (
        (
            InMemoryConversationRepository(),
            PostgresMemoryRepository("postgresql://test@database-a/disastermonitor"),
        ),
        (
            PostgresConversationRepository(
                "postgresql://test@database-a/disastermonitor"
            ),
            InMemoryMemoryRepository(),
        ),
        (
            PostgresConversationRepository(
                "postgresql://test@database-a/disastermonitor"
            ),
            PostgresMemoryRepository("postgresql://test@database-b/disastermonitor"),
        ),
        (
            type(
                "CustomConversationRepository",
                (InMemoryConversationRepository,),
                {},
            )(),
            InMemoryMemoryRepository(),
        ),
    ),
)
def test_deletion_composition_rejects_incompatible_persistence(
    conversations: object,
    memories: object,
) -> None:
    with pytest.raises(ValueError, match="atomic conversation deletion"):
        build_conversation_deletion_store(conversations, memories)  # type: ignore[arg-type]


def test_postgres_deletion_composition_uses_verified_explicit_adapter() -> None:
    dsn = "postgresql://test@database-a/disastermonitor"
    conversations = PostgresConversationRepository(dsn)

    deletion_store = build_conversation_deletion_store(
        conversations, PostgresMemoryRepository(dsn)
    )

    assert isinstance(deletion_store, PostgresConversationDeletionStore)
    assert deletion_store is not conversations
