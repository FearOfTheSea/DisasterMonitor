from datetime import UTC, datetime

import httpx
import pytest
from conftest import FakeLanguageModel

from disaster_monitor.application.disaster import (
    DisasterEvent,
    FactStatus,
    ProviderBatch,
    ReportedFact,
    SituationReport,
    SourceReference,
)
from disaster_monitor.application.services.current_disaster_report import (
    CurrentDisasterReportService,
)
from disaster_monitor.main import create_app

CURRENT_PROMPT = (
    "There was a recent earthquake in Japan. Please update me with the latest "
    "information about the damages in Japan."
)
NOW = datetime(2026, 8, 5, 12, 0, tzinfo=UTC)


def build_current_service(*, situation_error: Exception | None = None):
    event_source = SourceReference(
        publisher="JMA",
        title="Fixture earthquake",
        canonical_url="https://example.test/jma-event",
        published_at=NOW,
        updated_at=NOW,
        retrieved_at=NOW,
    )
    selected_event = DisasterEvent(
        event_id="jma:fixture-event",
        hazard="earthquake",
        location="Ishikawa, Japan",
        country="Japan",
        event_time=datetime(2026, 8, 5, 10, 0, tzinfo=UTC),
        source=event_source,
        latitude=37.0,
        longitude=137.0,
        magnitude=6.1,
        intensity="JMA 6-",
        depth_km=12,
    )

    class EventProvider:
        async def find_recent_events(self, query, *, now):
            return ProviderBatch((selected_event,))

    class SituationProvider:
        async def get_situation_reports(self, event, query, *, now):
            if situation_error:
                raise situation_error
            situation_source = SourceReference(
                publisher="ReliefWeb",
                title="Fixture situation update",
                canonical_url="https://example.test/reliefweb-update",
                published_at=NOW,
                updated_at=NOW,
                retrieved_at=NOW,
            )
            return ProviderBatch(
                (
                    SituationReport(
                        source=situation_source,
                        narrative="Four buildings were damaged.",
                        facts=(
                            ReportedFact(
                                category="buildings",
                                label="Buildings damaged",
                                value="4",
                                status=FactStatus.CONFIRMED,
                                source=situation_source,
                                event_id=event.event_id,
                                claim_id="buildings",
                            ),
                        ),
                        event_id=event.event_id,
                    ),
                )
            )

    return CurrentDisasterReportService(
        EventProvider(), SituationProvider(), clock=lambda: NOW
    )


@pytest.mark.asyncio
async def test_health_endpoint_does_not_need_the_model() -> None:
    app = create_app(model=FakeLanguageModel())
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


@pytest.mark.asyncio
async def test_readiness_and_assistant_use_injected_fake_model() -> None:
    model = FakeLanguageModel(response_text="The fake model can answer locally.")
    app = create_app(model=model)
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
async def test_assistant_validation_and_model_error_mapping() -> None:
    validation_app = create_app(model=FakeLanguageModel())
    error_app = create_app(
        model=FakeLanguageModel(error=ConnectionError("offline")),
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


@pytest.mark.asyncio
async def test_current_disaster_request_returns_event_report_and_source_metadata() -> (
    None
):
    app = create_app(
        model=FakeLanguageModel(error=ConnectionError("model is not needed")),
        current_disaster_report=build_current_service(),
    )

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/api/v1/assistant",
            json={"question": CURRENT_PROMPT},
        )

    body = response.json()
    assert response.status_code == 200
    assert body["response_type"] == "current_disaster"
    assert body["selected_event"]["event_id"] == "jma:fixture-event"
    assert "Situation summary" in body["message"]
    assert body["retrieval_time"] == NOW.isoformat().replace("+00:00", "Z")
    assert body["sources"][0]["canonical_url"] == "https://example.test/jma-event"
    assert any(source["publisher"] == "ReliefWeb" for source in body["sources"])
    assert body["sections"]


@pytest.mark.asyncio
async def test_current_disaster_partial_situation_failure() -> None:
    app = create_app(
        model=FakeLanguageModel(error=ConnectionError("model is not needed")),
        current_disaster_report=build_current_service(
            situation_error=TimeoutError("offline")
        ),
    )

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/api/v1/assistant", json={"question": CURRENT_PROMPT}
        )

    body = response.json()
    assert response.status_code == 200
    assert body["partial"] is True
    assert body["selected_event"]["location"] == "Ishikawa, Japan"
    assert any("situation-report source" in warning for warning in body["warnings"])
    assert "No reliable damage" in body["message"]


@pytest.mark.asyncio
async def test_current_disaster_is_honest_when_event_source_has_no_match() -> None:
    class EmptyEventProvider:
        async def find_recent_events(self, query, *, now):
            return ProviderBatch()

    class EmptySituationProvider:
        async def get_situation_reports(self, event, query, *, now):
            return ProviderBatch()

    app = create_app(
        model=FakeLanguageModel(error=ConnectionError("model is not needed")),
        current_disaster_report=CurrentDisasterReportService(
            EmptyEventProvider(), EmptySituationProvider(), clock=lambda: NOW
        ),
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/api/v1/assistant", json={"question": CURRENT_PROMPT}
        )

    body = response.json()
    assert response.status_code == 200
    assert body["response_type"] == "current_disaster_verification_failed"
    assert body["selected_event"] is None
    assert "could not verify" in body["message"]
