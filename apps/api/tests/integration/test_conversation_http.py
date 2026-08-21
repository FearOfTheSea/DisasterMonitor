import httpx
import pytest
from conftest import FakeLanguageModel

from disaster_monitor.infrastructure.conversations.memory_repository import (
    InMemoryConversationRepository,
)
from disaster_monitor.main import create_app


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
    assert all(len(request.messages) == 2 for request in model.requests)
    assert "First question?" not in model.requests[1].messages[1].content


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
