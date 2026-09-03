from datetime import timedelta

import httpx
import pytest
from assistant_http_fixtures import (
    CURRENT_PROMPT,
    JAPAN,
    NOW,
    build_current_service,
    injected_capabilities,
)
from conftest import FakeLanguageModel

from disaster_monitor.application.disaster import (
    ProviderBatch,
)
from disaster_monitor.application.dto import ModelToolCall
from disaster_monitor.application.services.current_disaster_report import (
    CurrentDisasterReportService,
)
from disaster_monitor.application.services.provider_registry import (
    ProviderCapabilities,
    ProviderRole,
)
from disaster_monitor.domain.disaster import (
    CorrelationStatus,
    CycloneMapCoordinate,
    CycloneMapGeometryKind,
    CycloneMapLayer,
    CycloneMapSemanticRole,
    Disaster,
    DisasterEvent,
    EventMeasurement,
    MeasurementKind,
    SituationReport,
    SourceAuthority,
    SourceReference,
    point_event_geometry,
)
from disaster_monitor.main import create_app


@pytest.mark.asyncio
async def test_health_endpoint_does_not_need_the_model() -> None:
    app = create_app(model=FakeLanguageModel())
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


@pytest.mark.asyncio
async def test_current_cyclone_serializes_supplemental_forecast_geometry() -> None:
    event_source = SourceReference(
        source_id="gdacs-tropical-cyclones",
        publisher="GDACS",
        title="Tropical Cyclone Fixture-26",
        canonical_url="https://www.gdacs.org/report.aspx?eventtype=TC&eventid=42",
        published_at=NOW,
        updated_at=NOW,
        retrieved_at=NOW,
        authority=SourceAuthority.SECONDARY,
    )
    event = DisasterEvent(
        event_id="gdacs:tc:42",
        disaster=Disaster.TROPICAL_CYCLONE,
        location="Pacific Ocean near Japan",
        country=JAPAN,
        event_time=NOW,
        source=event_source,
        geometry=point_event_geometry(25.0, 142.0, event_source),
    )
    product_source = SourceReference(
        source_id="noaa-nhc-cyclone-forecast",
        publisher="NOAA NHC/CPHC",
        title="Advisory #15 forecast track",
        canonical_url="https://www.nhc.noaa.gov/fixture-track.kmz",
        published_at=NOW,
        updated_at=NOW,
        retrieved_at=NOW,
        authority=SourceAuthority.NATIONAL_AUTHORITY,
    )
    layer = CycloneMapLayer(
        layer_id="noaa-nhc:EP112026:advisory-015:forecast-track",
        semantic_role=CycloneMapSemanticRole.FORECAST_TRACK,
        geometry_kind=CycloneMapGeometryKind.TRACK,
        coordinates=(
            CycloneMapCoordinate(25.1, 141.5, NOW + timedelta(hours=12)),
            CycloneMapCoordinate(25.4, 140.7, NOW + timedelta(hours=24)),
        ),
        source=product_source,
        issued_at=NOW,
        valid_from=NOW + timedelta(hours=12),
        valid_to=NOW + timedelta(hours=24),
        storm_id="EP112026",
        provisional=False,
        limitation="Forecast positions are not an observed storm footprint.",
        reconciliation="Unique name and source-backed center proximity match.",
    )

    class EventProvider:
        async def find_recent_events(self, query, *, now):
            return ProviderBatch((event,))

    class SituationProvider:
        async def get_situation_reports(self, selected, query, *, now):
            return ProviderBatch(
                (
                    SituationReport(
                        source=product_source,
                        narrative="Official forecast geometry is available.",
                        event_id=selected.event_id,
                        correlation=CorrelationStatus.MATCHED,
                        reported_event_time=selected.event_time,
                        locations=(selected.location,),
                        countries=(JAPAN.canonical_name,),
                        country_codes=(JAPAN.alpha3_code,),
                        disaster=Disaster.TROPICAL_CYCLONE,
                        provider_event_ids=("atcf:EP112026",),
                        supplemental_geometry=(layer,),
                    ),
                )
            )

    capabilities = (
        ProviderCapabilities(
            frozenset({ProviderRole.EVENT_DISCOVERY}),
            frozenset({Disaster.TROPICAL_CYCLONE}),
            None,
        ),
        ProviderCapabilities(
            frozenset({ProviderRole.SITUATION_EVIDENCE}),
            frozenset({Disaster.TROPICAL_CYCLONE}),
            None,
        ),
    )
    service = CurrentDisasterReportService(
        EventProvider(),
        SituationProvider(),
        provider_capabilities=capabilities,
        clock=lambda: NOW,
    )
    app = create_app(model=FakeLanguageModel(), current_disaster_report=service)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/api/v1/assistant",
            json={"question": "What is the latest tropical cyclone in Japan?"},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["selected_event"]["geometry"]["coordinates"] == [
        {"latitude": 25.0, "longitude": 142.0}
    ]
    assert body["selected_event"]["supplemental_geometry"] == [
        {
            "layer_id": layer.layer_id,
            "semantic_role": "forecast_track",
            "geometry_kind": "track",
            "coordinates": [
                {
                    "latitude": 25.1,
                    "longitude": 141.5,
                    "valid_at": "2026-08-06T00:00:00Z",
                },
                {
                    "latitude": 25.4,
                    "longitude": 140.7,
                    "valid_at": "2026-08-06T12:00:00Z",
                },
            ],
            "source": {
                "source_id": product_source.source_id,
                "publisher": product_source.publisher,
                "title": product_source.title,
                "canonical_url": product_source.canonical_url,
                "published_at": "2026-08-05T12:00:00Z",
                "updated_at": "2026-08-05T12:00:00Z",
                "retrieved_at": "2026-08-05T12:00:00Z",
                "snapshot_id": None,
            },
            "issued_at": "2026-08-05T12:00:00Z",
            "valid_from": "2026-08-06T00:00:00Z",
            "valid_to": "2026-08-06T12:00:00Z",
            "storm_id": "EP112026",
            "provisional": False,
            "limitation": layer.limitation,
            "reconciliation": layer.reconciliation,
            "wind_threshold": None,
            "wind_threshold_unit": None,
        }
    ]


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
        "conversation_id": response.json()["conversation_id"],
        "model": "fake-qwen",
        "operator_actions": [],
    }
    assert "What is this map for?" in model.requests[0].messages[1].content


@pytest.mark.asyncio
async def test_map_context_question_cannot_be_reclassified_by_agent_model() -> None:
    class ShouldNotInterpretMapQuestion:
        calls = 0

        async def interpret(self, question):
            self.calls += 1
            raise AssertionError(
                "Non-disaster map questions must bypass interpretation"
            )

        async def propose_plan(self, task, tool_descriptions):
            raise AssertionError("A general map question must not create a plan")

        async def review_progress(self, task, completed_steps):
            raise AssertionError("A general map question must not create a review")

    question = (
        "What is this map for, and what can you infer from the current map center "
        "and zoom? Do not claim to see unavailable layers."
    )
    agent_model = ShouldNotInterpretMapQuestion()
    model = FakeLanguageModel(response_text="I can explain the supplied map context.")
    app = create_app(model=model, agent_model=agent_model)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/api/v1/assistant",
            json={
                "question": question,
                "map_view": {
                    "center_latitude": 21.03,
                    "center_longitude": 105.85,
                    "zoom": 10,
                },
            },
        )

    assert response.status_code == 200
    assert response.json()["message"] == "I can explain the supplied map context."
    assert response.json()["model"] == "fake-qwen"
    assert agent_model.calls == 0
    assert len(model.requests) == 1


@pytest.mark.asyncio
async def test_general_map_command_executes_the_agent_country_tool() -> None:
    model = FakeLanguageModel(
        response_text="",
        tool_calls=(ModelToolCall("fit_country", {"country_code": "JPN"}),),
    )
    app = create_app(model=model)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/api/v1/assistant",
            json={
                "question": "Zoom into Japan.",
                "map_view": {
                    "center_latitude": 21.03,
                    "center_longitude": 105.85,
                    "zoom": 10,
                },
            },
        )

    assert response.status_code == 200
    assert response.json() == {
        "message": "Showing Japan on the map.",
        "conversation_id": response.json()["conversation_id"],
        "model": "fake-qwen",
        "map_action": {
            "type": "fit_bounds",
            "bounds": [122.0, 20.0, 154.0, 46.0],
            "label": "Japan",
            "max_zoom": 10.0,
        },
        "operator_actions": [],
    }
    assert [tool.name for tool in model.requests[0].tools] == ["fit_country"]


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
    assert body["selected_event"]["event_id"] == "global-catalog:fixture-event"
    assert body["selected_event"]["geography_status"] == "in_country"
    assert body["selected_event"]["geometry"] == {
        "kind": "point",
        "coordinates": [{"latitude": 37.0, "longitude": 137.0}],
        "description": None,
        "source_id": "fixture-events",
        "estimated": False,
    }
    assert body["selected_event"]["measurements"] == [
        {
            "kind": "magnitude",
            "value": 6.1,
            "unit": None,
            "source_id": "fixture-events",
        },
        {
            "kind": "intensity",
            "value": "Global Catalog 6-",
            "unit": None,
            "source_id": "fixture-events",
        },
        {
            "kind": "depth",
            "value": 12.0,
            "unit": "km",
            "source_id": "fixture-events",
        },
    ]
    assert body["map_action"] == {
        "type": "fit_bounds",
        "bounds": [137.0, 37.0, 137.0, 37.0],
        "label": "Ishikawa, Japan",
        "max_zoom": 10.0,
    }
    assert "Situation summary" in body["message"]
    assert body["retrieval_time"] == NOW.isoformat().replace("+00:00", "Z")
    assert body["sources"][0]["source_id"] == "fixture-events"
    assert (
        body["sources"][0]["canonical_url"]
        == "https://example.test/global-catalog-event"
    )
    assert any(source["publisher"] == "Global Reports" for source in body["sources"])
    assert body["sections"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("question", "country_code"),
    (
        ("Any news about earthquakes in Vietnam", "VNM"),
        ("Any news about earthquakes in Venezuela?", "VEN"),
    ),
)
async def test_earthquake_news_never_falls_through_to_general_model(
    question: str, country_code: str
) -> None:
    received_queries = []

    class CountryEventProvider:
        async def find_recent_events(self, query, *, now):
            received_queries.append(query)
            source = SourceReference(
                source_id="fixture-global-earthquakes",
                publisher="Fixture scientific authority",
                title=f"Fixture earthquake in {query.country.canonical_name}",
                canonical_url="https://example.test/global-earthquake",
                published_at=now,
                updated_at=now,
                retrieved_at=now,
            )
            return ProviderBatch(
                (
                    DisasterEvent(
                        event_id=f"fixture:{query.country.alpha3_code.lower()}",
                        disaster=Disaster.EARTHQUAKE,
                        location=query.country.canonical_name,
                        country=query.country,
                        event_time=now,
                        source=source,
                        measurements=(
                            EventMeasurement(
                                MeasurementKind.MAGNITUDE, 5.0, source=source
                            ),
                        ),
                    ),
                )
            )

    class EmptySituationProvider:
        async def get_situation_reports(self, event, query, *, now):
            return ProviderBatch()

    model = FakeLanguageModel(error=AssertionError("general model must not be called"))
    service = CurrentDisasterReportService(
        CountryEventProvider(),
        EmptySituationProvider(),
        provider_capabilities=injected_capabilities(),
        clock=lambda: NOW,
    )
    app = create_app(model=model, current_disaster_report=service)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post("/api/v1/assistant", json={"question": question})

    body = response.json()
    assert response.status_code == 200
    assert body["response_type"] == "current_disaster"
    assert body["selected_event"]["event_id"] == f"fixture:{country_code.lower()}"
    assert body["investigation"]["country"] == country_code
    assert [query.country_code for query in received_queries] == [country_code]
    assert model.requests == []
