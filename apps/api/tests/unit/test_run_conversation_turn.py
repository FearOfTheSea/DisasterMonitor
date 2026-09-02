from datetime import UTC, datetime

import pytest

from disaster_monitor.application.dto import AssistantAnswer
from disaster_monitor.application.media import (
    DisasterMediaGallery,
    DisasterMediaItem,
    MediaAssociationStatus,
    MediaContentRole,
    MediaCreditKind,
    MediaRightsStatus,
)
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


class MediaAssistant(FakeAssistant):
    async def execute(self, question: str, *, conversation_id: str, **kwargs):
        answer = await super().execute(
            question, conversation_id=conversation_id, **kwargs
        )
        item = DisasterMediaItem(
            media_id="media:" + "a" * 64 + ":png",
            event_id="event-1",
            physical_event_id="physical-event-1",
            source_id="source-1",
            publisher="Publisher",
            source_page_url="https://example.test/article",
            caption="Rescue crews after the earthquake.",
            credit="Agency",
            credit_kind=MediaCreditKind.AGENCY,
            published_at=datetime(2026, 8, 21, tzinfo=UTC),
            captured_at=None,
            license_name=None,
            license_url=None,
            rights_status=MediaRightsStatus.SOURCE_PREVIEW,
            role=MediaContentRole.RESCUE_EFFORT,
            association_status=MediaAssociationStatus.CORROBORATED,
            association_rule_ids=("media.association.publication_window",),
            association_detail="The event metadata agrees.",
            uncertainty="Contextual source media.",
            content_sha256="a" * 64,
            width=640,
            height=360,
        )
        return AssistantAnswer(
            message=answer.message,
            conversation_id=answer.conversation_id,
            model=answer.model,
            response_type="current_disaster_earthquake",
            warnings=("Report warning",),
            media_gallery=DisasterMediaGallery(
                event_id="event-1",
                physical_event_id="physical-event-1",
                generated_at=datetime(2026, 8, 21, tzinfo=UTC),
                items=(item,),
                rejected_count=2,
                provider_ids=("fixture-media",),
                warnings=("Gallery warning",),
            ),
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


@pytest.mark.asyncio
async def test_assistant_turn_persists_versioned_structured_answer() -> None:
    repository = InMemoryConversationRepository()
    result = await RunConversationTurn(MediaAssistant(), repository).execute("Question")

    conversation = await repository.get(result.conversation_id)

    assert conversation is not None
    assistant_message = conversation.messages[-1]
    payload = getattr(assistant_message, "assistant_payload", None)
    assert payload is not None
    assert payload.schema_version == "assistant-answer.v3"
    media_item = payload.data["media_gallery"]["items"][0]
    assert media_item["source_id"] == "source-1"
    assert media_item["caption"] == "Rescue crews after the earthquake."
    assert media_item["credit"] == "Agency"
    assert media_item["credit_kind"] == "agency"
    assert media_item["rights_status"] == "source_preview"
    assert media_item["association_status"] == "corroborated"
    assert media_item["published_at"] == "2026-08-21T00:00:00+00:00"
    assert payload.data["media_gallery"]["warnings"] == ["Gallery warning"]
