from datetime import UTC, datetime

import pytest

from disaster_monitor.application.dto import AssistantAnswer
from disaster_monitor.application.use_cases.run_conversation_turn import (
    RunConversationTurn,
)
from disaster_monitor.domain.errors import ConversationNotFoundError
from disaster_monitor.infrastructure.conversations.memory_repository import (
    InMemoryConversationRepository,
)


class FakeAssistant:
    def __init__(self) -> None:
        self.questions: list[tuple[str, str]] = []
        self.histories = []

    async def execute(self, question: str, *, conversation_id: str, **kwargs):
        self.histories.append(kwargs["conversation_history"])
        self.questions.append((question, conversation_id))
        return AssistantAnswer(
            message=f"Answer to {question}",
            conversation_id=conversation_id,
            model="fake-model",
        )


@pytest.mark.asyncio
async def test_missing_id_creates_conversation_and_appends_normalized_turn() -> None:
    repository = InMemoryConversationRepository()
    assistant = FakeAssistant()
    use_case = RunConversationTurn(
        assistant, repository, clock=lambda: datetime(2026, 8, 21, tzinfo=UTC)
    )

    result = await use_case.execute("  What   is here?  ")

    conversation = await repository.get(result.conversation_id)
    assert conversation is not None
    assert [
        (message.role.value, message.content) for message in conversation.messages
    ] == [
        ("user", "What is here?"),
        ("assistant", "Answer to What is here?"),
    ]
    assert assistant.questions == [("What is here?", result.conversation_id)]
    assert assistant.histories == [()]


@pytest.mark.asyncio
async def test_existing_id_is_reused_and_conversations_remain_isolated() -> None:
    repository = InMemoryConversationRepository()
    assistant = FakeAssistant()
    use_case = RunConversationTurn(assistant, repository)

    first = await use_case.execute("First question")
    second = await use_case.execute("Second question")
    continued = await use_case.execute(
        "Follow-up", conversation_id=first.conversation_id
    )

    assert continued.conversation_id == first.conversation_id
    first_conversation = await repository.get(first.conversation_id)
    second_conversation = await repository.get(second.conversation_id)
    assert first_conversation is not None and second_conversation is not None
    assert [message.content for message in first_conversation.messages] == [
        "First question",
        "Answer to First question",
        "Follow-up",
        "Answer to Follow-up",
    ]
    assert [message.content for message in second_conversation.messages] == [
        "Second question",
        "Answer to Second question",
    ]
    assert assistant.histories[0] == ()
    assert assistant.histories[1] == ()
    assert [message.content for message in assistant.histories[2]] == [
        "First question",
        "Answer to First question",
    ]


@pytest.mark.asyncio
async def test_unknown_id_fails_without_creating_caller_selected_state() -> None:
    repository = InMemoryConversationRepository()
    use_case = RunConversationTurn(FakeAssistant(), repository)

    with pytest.raises(ConversationNotFoundError):
        await use_case.execute("Question", conversation_id="deleted-conversation")

    assert await repository.get("deleted-conversation") is None
