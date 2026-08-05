from datetime import UTC, datetime

import httpx
import pytest
from conftest import FakeDisasterInformationProvider, FakeLanguageModel

from disaster_monitor.application.dto import (
    DisasterInformationItem,
    DisasterInformationResult,
)
from disaster_monitor.main import create_app


def _provider() -> FakeDisasterInformationProvider:
    return FakeDisasterInformationProvider(
        result=DisasterInformationResult(
            query="test",
            retrieved_at=datetime(2026, 8, 5, tzinfo=UTC),
            items=(),
        )
    )


@pytest.mark.asyncio
async def test_health_endpoint_does_not_need_the_model() -> None:
    app = create_app(
        model=FakeLanguageModel(),
        disaster_information_provider=_provider(),
    )
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


@pytest.mark.asyncio
async def test_readiness_and_assistant_use_injected_fake_model() -> None:
    model = FakeLanguageModel(response_text="The fake model can answer locally.")
    app = create_app(model=model, disaster_information_provider=_provider())
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        readiness = await client.get("/api/v1/ready")
        response = await client.post(
            "/api/v1/assistant",
            json={
                "question": "  What is this map for? ",
                "conversation_id": "test-session",
                "map_view": {
                    "center_latitude": 21.03,
                    "center_longitude": 105.85,
                    "zoom": 10,
                },
            },
        )

    assert readiness.status_code == 200
    assert readiness.json() == {
        "status": "ready",
        "ollama_available": True,
        "model_available": True,
        "model": "fake-qwen",
    }
    assert response.status_code == 200
    assert response.json() == {
        "message": "The fake model can answer locally.",
        "conversation_id": "test-session",
        "model": "fake-qwen",
    }
    assert "What is this map for?" in model.requests[0].messages[1].content


@pytest.mark.asyncio
async def test_http_request_for_latest_japan_damage_uses_current_information() -> None:
    provider = FakeDisasterInformationProvider(
        result=DisasterInformationResult(
            query="Japan earthquake latest damage casualties injuries official updates",
            retrieved_at=datetime(2026, 8, 5, 7, 0, tzinfo=UTC),
            items=(
                DisasterInformationItem(
                    title="Preliminary damage update",
                    source="NHK",
                    published_at=datetime(2026, 8, 5, 6, 30, tzinfo=UTC),
                    url="https://example.test/report",
                    summary="Assessment continues.",
                ),
            ),
        )
    )
    model = FakeLanguageModel(response_text="Đã cập nhật từ các nguồn hiện có.")
    app = create_app(model=model, disaster_information_provider=provider)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.post(
            "/api/v1/assistant",
            json={
                "question": (
                    "Thử xem dùng hệ thống này để cập nhật thông tin mới nhất "
                    "về thiệt hại tại Nhật Bản xem có đc k nhé"
                )
            },
        )

    assert response.status_code == 200
    assert provider.queries == [
        "Japan earthquake latest damage casualties injuries official updates"
    ]
    assert "source: NHK" in model.requests[0].messages[1].content


@pytest.mark.asyncio
async def test_assistant_validation_and_model_error_mapping() -> None:
    validation_app = create_app(
        model=FakeLanguageModel(),
        disaster_information_provider=_provider(),
    )
    error_app = create_app(
        model=FakeLanguageModel(error=ConnectionError("offline")),
        disaster_information_provider=_provider(),
    )

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=validation_app), base_url="http://test"
    ) as client:
        validation_response = await client.post(
            "/api/v1/assistant", json={"question": "   "}
        )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=error_app), base_url="http://test"
    ) as client:
        error_response = await client.post(
            "/api/v1/assistant", json={"question": "Will the model answer?"}
        )

    assert validation_response.status_code == 422
    assert error_response.status_code == 503
    assert "local model is unavailable" in error_response.json()["detail"]
