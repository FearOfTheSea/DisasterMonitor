from datetime import UTC, datetime

import httpx
import pytest
from conftest import FakeLanguageModel

from disaster_monitor.application.dto import AssistantAnswer, InvestigationSummary
from disaster_monitor.application.media import (
    DisasterMediaGallery,
    DisasterMediaItem,
    MediaAssociationStatus,
    MediaContentRole,
    MediaCreditKind,
    MediaRightsStatus,
    StoredMediaAsset,
)
from disaster_monitor.application.use_cases.run_conversation_turn import (
    RunConversationTurn,
)
from disaster_monitor.domain.conversation import (
    Conversation,
    ConversationMessage,
    ConversationRole,
)
from disaster_monitor.domain.memory import MemoryLifecycleStatus
from disaster_monitor.infrastructure.configuration import Settings
from disaster_monitor.infrastructure.conversations.memory_repository import (
    InMemoryConversationRepository,
)
from disaster_monitor.infrastructure.memory.memory_repository import (
    InMemoryMemoryRepository,
)
from disaster_monitor.main import create_app

NOW = datetime(2026, 8, 21, 10, tzinfo=UTC)


@pytest.mark.asyncio
async def test_conversation_turn_persists_typed_memory_and_deletion_hides_it() -> None:
    conversations = InMemoryConversationRepository()
    memories = InMemoryMemoryRepository()

    class Assistant:
        async def execute(self, question: str, *, conversation_id: str, **kwargs):
            return AssistantAnswer(
                message="A current source-backed answer.",
                conversation_id=conversation_id,
                model="fixture-agent",
                investigation=InvestigationSummary(
                    status="completed",
                    task_summary=question,
                    disaster="flood",
                    country="TST",
                    information_needs=("event_overview",),
                    output_modalities=("text",),
                    actions=("Retrieved current evidence.",),
                    source_ids=("test-source",),
                    evidence_count=1,
                    capability_gaps=(),
                    termination_reason="grounded_answer_composed",
                    physical_event_id="physical-event:test",
                    evidence_state_version="state:current",
                ),
            )

    app = create_app(
        settings=Settings(
            _env_file=None,
            long_term_memory_enabled=True,
            event_media_enabled=False,
        ),
        model=FakeLanguageModel(),
        conversation_repository=conversations,
        memory_repository=memories,
    )
    app.state.run_conversation_turn = RunConversationTurn(
        Assistant(),
        conversations,
        clock=lambda: NOW,
        memory_store=memories,
        memory_enabled=True,
    )

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        created = await client.post(
            "/api/v1/assistant", json={"question": "What changed?"}
        )
        conversation_id = created.json()["conversation_id"]
        stored = await memories.list_for_scope(conversation_id, "physical-event:test")
        deleted = await client.delete(f"/api/v1/conversations/{conversation_id}")

    assert created.status_code == 200
    assert len(stored) == 1
    assert stored[0].world_state_version == "state:current"
    assert stored[0].may_satisfy_current_evidence is False
    assert deleted.status_code == 204
    after_delete = await memories.list_for_scope(conversation_id, "physical-event:test")
    assert after_delete[0].status is MemoryLifecycleStatus.DELETED


@pytest.mark.asyncio
async def test_conversation_http_lifecycle_and_assistant_persistence() -> None:
    model = FakeLanguageModel(response_text="A persisted answer.")
    app = create_app(
        model=model,
        conversation_repository=InMemoryConversationRepository(),
    )

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        created = await client.post(
            "/api/v1/assistant", json={"question": "  First   question? "}
        )
        conversation_id = created.json()["conversation_id"]
        continued = await client.post(
            "/api/v1/assistant",
            json={
                "question": "Follow-up?",
                "conversation_id": conversation_id,
            },
        )
        listed = await client.get("/api/v1/conversations")
        loaded = await client.get(f"/api/v1/conversations/{conversation_id}")

    assert created.status_code == 200
    assert continued.status_code == 200
    assert listed.status_code == 200
    assert listed.json()[0]["conversation_id"] == conversation_id
    assert listed.json()[0]["preview"] == "First question?"
    assert loaded.status_code == 200
    assert [message["content"] for message in loaded.json()["messages"]] == [
        "First question?",
        "A persisted answer.",
        "Follow-up?",
        "A persisted answer.",
    ]
    assert len(model.requests) == 2
    assert [message.role for message in model.requests[1].messages] == [
        "system",
        "user",
        "assistant",
        "user",
    ]
    assert [message.content for message in model.requests[1].messages[1:3]] == [
        "First question?",
        "A persisted answer.",
    ]
    assert "First question?" not in model.requests[1].messages[3].content


@pytest.mark.asyncio
async def test_conversation_http_rejects_unknown_and_deletes_cascade() -> None:
    app = create_app(
        model=FakeLanguageModel(),
        conversation_repository=InMemoryConversationRepository(),
    )

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        created = await client.post("/api/v1/assistant", json={"question": "Question"})
        conversation_id = created.json()["conversation_id"]
        unknown = await client.post(
            "/api/v1/assistant",
            json={"question": "Question", "conversation_id": "missing"},
        )
        deleted = await client.delete(f"/api/v1/conversations/{conversation_id}")
        loaded = await client.get(f"/api/v1/conversations/{conversation_id}")
        deleted_again = await client.delete(f"/api/v1/conversations/{conversation_id}")

    assert unknown.status_code == 404
    assert deleted.status_code == 204
    assert loaded.status_code == 404
    assert deleted_again.status_code == 404


@pytest.mark.asyncio
async def test_reloaded_conversation_reconstructs_media_report_and_legacy_text() -> (
    None
):
    repository = InMemoryConversationRepository()
    media_id = "media:" + "a" * 64 + ":png"
    media_bytes = b"persisted-image"

    class Store:
        def put(self, media):
            raise AssertionError("The fixture answer already references stored media.")

        def get(self, requested_id):
            if requested_id != media_id:
                return None
            return StoredMediaAsset(media_id, media_bytes, "image/png", "a" * 64)

    class Assistant:
        async def execute(self, question: str, *, conversation_id: str, **kwargs):
            item = DisasterMediaItem(
                media_id=media_id,
                event_id="event-1",
                physical_event_id="physical-event-1",
                source_id="source-1",
                publisher="Publisher",
                source_page_url="https://example.test/article",
                caption="Rescue crews after the earthquake.",
                credit="Agency",
                credit_kind=MediaCreditKind.AGENCY,
                published_at=NOW,
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
                message="Source-backed report.",
                conversation_id=conversation_id,
                model="fixture-agent",
                response_type="current_disaster_earthquake",
                warnings=("Report warning",),
                media_gallery=DisasterMediaGallery(
                    event_id="event-1",
                    physical_event_id="physical-event-1",
                    generated_at=NOW,
                    items=(item,),
                    rejected_count=2,
                    provider_ids=("fixture-media",),
                    warnings=("Gallery warning",),
                ),
            )

    class Discovery:
        async def discover(self, context):
            return None

    app = create_app(
        model=FakeLanguageModel(),
        conversation_repository=repository,
        media_asset_store=Store(),
        event_media=Discovery(),
    )
    app.state.run_conversation_turn = RunConversationTurn(
        Assistant(), repository, clock=lambda: NOW
    )
    await repository.create(Conversation("legacy", NOW, NOW))
    await repository.append(
        ConversationMessage(
            "legacy-message",
            "legacy",
            ConversationRole.ASSISTANT,
            "Legacy answer.",
            NOW,
        )
    )

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        created = await client.post(
            "/api/v1/assistant", json={"question": "What happened?"}
        )
        conversation_id = created.json()["conversation_id"]
        loaded = await client.get(f"/api/v1/conversations/{conversation_id}")
        legacy = await client.get("/api/v1/conversations/legacy")
        gallery_url = loaded.json()["messages"][1]["assistant_response"][
            "media_gallery"
        ]["items"][0]["image_url"]
        image = await client.get(gallery_url)

    historical = loaded.json()["messages"][1]["assistant_response"]
    assert historical == created.json()
    assert historical["warnings"] == ["Report warning"]
    assert historical["media_gallery"]["rejected_count"] == 2
    assert historical["media_gallery"]["warnings"] == ["Gallery warning"]
    assert historical["media_gallery"]["items"][0]["source_id"] == "source-1"
    assert historical["media_gallery"]["items"][0]["image_url"] == gallery_url
    assert image.content == media_bytes
    assert legacy.json()["messages"] == [
        {
            "id": "legacy-message",
            "role": "assistant",
            "content": "Legacy answer.",
            "created_at": legacy.json()["messages"][0]["created_at"],
            "assistant_response": None,
        }
    ]
