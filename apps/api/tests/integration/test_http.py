import base64
from datetime import UTC, datetime
from hashlib import sha256

import httpx
import pytest
from conftest import FakeLanguageModel

from disaster_monitor.application.disaster import (
    GeographicScope,
    ProviderBatch,
    WorldwideDisasterEvent,
)
from disaster_monitor.application.dto import ModelRequest, ModelToolCall
from disaster_monitor.application.media import (
    DisasterMediaGallery,
    DisasterMediaItem,
    MediaAssociationStatus,
    MediaContentRole,
    MediaCreditKind,
    MediaRightsStatus,
    StoredMediaAsset,
)
from disaster_monitor.application.multimodal import (
    VisualModelPrediction,
    VisualModelReadiness,
)
from disaster_monitor.application.services.current_disaster_report import (
    CurrentDisasterReportService,
)
from disaster_monitor.application.services.provider_registry import (
    ProviderCapabilities,
    ProviderRegistration,
    ProviderRegistry,
    ProviderRole,
)
from disaster_monitor.application.services.worldwide_disaster import (
    WorldwideDisasterReportService,
)
from disaster_monitor.domain.disaster import (
    DisasterEvent,
    FactStatus,
    Hazard,
    ReportedFact,
    SituationReport,
    SourceAuthority,
    SourceReference,
)
from disaster_monitor.domain.multimodal import (
    DamageLevel,
    VisualAnalysisConfiguration,
)
from disaster_monitor.infrastructure.geography.static_country_catalog import (
    StaticCountryCatalog,
)
from disaster_monitor.main import create_app

CURRENT_PROMPT = (
    "There was a recent earthquake in Japan. Please update me with the latest "
    "information about the damages in Japan."
)
NOW = datetime(2026, 8, 5, 12, 0, tzinfo=UTC)
AUGUST_2026_PROMPT = (
    "Please give me the latest information about the earthquake in Japan on "
    "August 5, 2026."
)
CATALOG = StaticCountryCatalog()
JAPAN = CATALOG.get_by_alpha3("JPN")
VENEZUELA = CATALOG.get_by_alpha3("VEN")
assert JAPAN is not None and VENEZUELA is not None


def build_current_service(
    *,
    situation_error: Exception | None = None,
    fact_category: str = "buildings",
    fact_label: str = "Buildings damaged",
    fact_value: str = "4",
    fact_status: FactStatus = FactStatus.CONFIRMED,
):
    event_source = SourceReference(
        source_id="fixture-events",
        publisher="JMA",
        title="Fixture earthquake",
        canonical_url="https://example.test/jma-event",
        published_at=NOW,
        updated_at=NOW,
        retrieved_at=NOW,
    )
    selected_event = DisasterEvent(
        event_id="jma:fixture-event",
        hazard=Hazard.EARTHQUAKE,
        location="Ishikawa, Japan",
        country=JAPAN,
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
                source_id="fixture-situation-reports",
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
                        narrative=f"{fact_label}: {fact_value}.",
                        facts=(
                            ReportedFact(
                                category=fact_category,
                                label=fact_label,
                                value=fact_value,
                                status=fact_status,
                                source=situation_source,
                                event_id=event.event_id,
                                claim_id=fact_category,
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
    assert body["selected_event"]["event_id"] == "jma:fixture-event"
    assert body["selected_event"]["geography_status"] == "in_country"
    assert body["selected_event"]["latitude"] == 37.0
    assert body["selected_event"]["longitude"] == 137.0
    assert body["map_action"] == {
        "type": "fit_bounds",
        "bounds": [137.0, 37.0, 137.0, 37.0],
        "label": "Ishikawa, Japan",
        "max_zoom": 10.0,
    }
    assert "Situation summary" in body["message"]
    assert body["retrieval_time"] == NOW.isoformat().replace("+00:00", "Z")
    assert body["sources"][0]["source_id"] == "fixture-events"
    assert body["sources"][0]["canonical_url"] == "https://example.test/jma-event"
    assert any(source["publisher"] == "ReliefWeb" for source in body["sources"])
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
                        hazard=Hazard.EARTHQUAKE,
                        location=query.country.canonical_name,
                        country=query.country,
                        event_time=now,
                        source=source,
                        magnitude=5.0,
                    ),
                )
            )

    class EmptySituationProvider:
        async def get_situation_reports(self, event, query, *, now):
            return ProviderBatch()

    model = FakeLanguageModel(error=AssertionError("general model must not be called"))
    service = CurrentDisasterReportService(
        CountryEventProvider(), EmptySituationProvider(), clock=lambda: NOW
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


@pytest.mark.asyncio
async def test_explicit_worldwide_earthquake_news_uses_global_usgs_scope() -> None:
    source = SourceReference(
        source_id="usgs-earthquakes",
        publisher="United States Geological Survey",
        title="Fixture worldwide earthquake",
        canonical_url="https://earthquake.usgs.gov/earthquakes/eventpage/global",
        published_at=NOW,
        updated_at=NOW,
        retrieved_at=NOW,
        authority=SourceAuthority.SCIENTIFIC_AUTHORITY,
    )

    class GlobalProvider:
        async def find_worldwide_events(self, query, *, now):
            return ProviderBatch(
                (
                    WorldwideDisasterEvent(
                        event_id="usgs:global",
                        hazard=Hazard.EARTHQUAKE,
                        location="South Pacific Ocean",
                        event_time=now,
                        source=source,
                        latitude=-20.0,
                        longitude=-170.0,
                        magnitude=6.4,
                        depth_km=18.0,
                        provider_ids=("usgs:global",),
                    ),
                )
            )

    worldwide_report = WorldwideDisasterReportService(
        ProviderRegistry(
            (
                ProviderRegistration(
                    "USGS",
                    GlobalProvider(),
                    ProviderCapabilities(
                        roles=frozenset({ProviderRole.EVENT_DISCOVERY}),
                        hazards=frozenset({Hazard.EARTHQUAKE}),
                        country_codes=None,
                        geographic_scopes=frozenset({GeographicScope.WORLDWIDE}),
                    ),
                    source_id="usgs-earthquakes",
                    allowed_hosts=frozenset({"earthquake.usgs.gov"}),
                    event_provider=GlobalProvider(),
                    worldwide_provider=GlobalProvider(),
                ),
            )
        ),
        clock=lambda: NOW,
    )

    class RecordingMediaDiscovery:
        def __init__(self) -> None:
            self.contexts = []

        async def discover(self, context):
            self.contexts.append(context)
            return None

    class EmptyMediaStore:
        def put(self, media):
            raise AssertionError("No media should be stored by this fixture.")

        def get(self, media_id):
            return None

    media_discovery = RecordingMediaDiscovery()
    model = FakeLanguageModel(error=AssertionError("general model must not be called"))
    app = create_app(
        model=model,
        current_disaster_report=build_current_service(),
        worldwide_disaster_report=worldwide_report,
        event_media=media_discovery,
        media_asset_store=EmptyMediaStore(),
    )

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/api/v1/assistant",
            json={"question": "Any earthquake news worldwide?"},
        )

    body = response.json()
    assert response.status_code == 200
    assert body["response_type"] == "current_disaster_global_earthquake"
    assert body["selected_event"]["event_id"] == "usgs:global"
    assert body["map_action"]["label"] == "South Pacific Ocean"
    assert body["investigation"]["country"] is None
    assert body["investigation"]["geographic_scope"] == "worldwide"
    assert body["investigation"]["source_ids"] == ["usgs-earthquakes"]
    assert len(media_discovery.contexts) == 1
    assert media_discovery.contexts[0].event_id == "usgs:global"
    assert media_discovery.contexts[0].country_code is None
    assert model.requests == []


@pytest.mark.asyncio
async def test_current_event_returns_three_typed_source_photos_and_serves_bytes() -> (
    None
):
    media_id = "media:" + "a" * 32
    media_bytes = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk"
        "+A8AAQUBAScY42YAAAAASUVORK5CYII="
    )
    checksum = sha256(media_bytes).hexdigest()

    class Store:
        def put(self, media):
            raise AssertionError("The fixture discovery already stored its media.")

        def get(self, requested_id):
            if requested_id != media_id:
                return None
            return StoredMediaAsset(media_id, media_bytes, "image/png", checksum)

    class Discovery:
        async def discover(self, context):
            assert context.event_id == "jma:fixture-event"
            items = tuple(
                DisasterMediaItem(
                    media_id=media_id,
                    event_id=context.event_id,
                    physical_event_id=context.physical_event_id,
                    source_id=f"fixture-photo-source-{index}",
                    publisher=f"Fixture publisher {index}",
                    source_page_url=f"https://example.test/photo-{index}",
                    caption=f"Rescue response photo {index}",
                    credit=f"Fixture agency {index}",
                    credit_kind=MediaCreditKind.AGENCY,
                    published_at=NOW,
                    captured_at=None,
                    license_name=None,
                    license_url=None,
                    rights_status=MediaRightsStatus.SOURCE_PREVIEW,
                    role=MediaContentRole.RESCUE_EFFORT,
                    association_status=MediaAssociationStatus.CORROBORATED,
                    association_rule_ids=(
                        "media.association.publication_window",
                        "media.association.hazard_text",
                        "media.association.country_text",
                    ),
                    association_detail="Source metadata matches the selected event.",
                    uncertainty="Source-associated preview, not a verified fact.",
                    content_sha256=checksum,
                    width=640,
                    height=360,
                )
                for index in range(1, 4)
            )
            return DisasterMediaGallery(
                event_id=context.event_id,
                physical_event_id=context.physical_event_id,
                generated_at=NOW,
                items=items,
                rejected_count=1,
                provider_ids=("fixture-media",),
            )

    app = create_app(
        model=FakeLanguageModel(error=AssertionError("model must not be called")),
        current_disaster_report=build_current_service(),
        event_media=Discovery(),
        media_asset_store=Store(),
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/api/v1/assistant", json={"question": CURRENT_PROMPT}
        )
        image_response = await client.get(f"/api/v1/media/{media_id}")

    body = response.json()
    assert response.status_code == 200
    assert body["media_gallery"]["event_id"] == "jma:fixture-event"
    assert len(body["media_gallery"]["items"]) == 3
    assert body["media_gallery"]["rejected_count"] == 1
    assert body["media_gallery"]["items"][0]["image_url"].endswith(
        f"/api/v1/media/{media_id}"
    )
    assert image_response.status_code == 200
    assert image_response.headers["content-type"] == "image/png"
    assert image_response.content == media_bytes


@pytest.mark.asyncio
async def test_current_disaster_routes_one_normalized_japan_query_without_model() -> (
    None
):
    retrieval_time = datetime(2026, 8, 6, 3, 0, tzinfo=UTC)
    target_time = datetime(2026, 8, 5, 14, 30, tzinfo=UTC)
    received_event_queries = []
    received_situation_queries = []

    class FailIfCalledModel(FakeLanguageModel):
        async def generate(self, request: ModelRequest):
            self.requests.append(request)
            raise AssertionError("GENERAL-MODEL-SENTINEL")

    target_source = SourceReference(
        source_id="fixture-events",
        publisher="JMA",
        title="Ishikawa target event",
        canonical_url="https://example.test/jma-ishikawa",
        published_at=target_time,
        updated_at=target_time,
        retrieved_at=retrieval_time,
    )
    target_event = DisasterEvent(
        event_id="jma:202608051430",
        hazard=Hazard.EARTHQUAKE,
        location="Ishikawa, Japan",
        country=JAPAN,
        event_time=target_time,
        source=target_source,
        latitude=37.0,
        longitude=137.0,
        magnitude=6.1,
        intensity="JMA 6-",
        provider_ids=("jma:202608051430", "usgs:fixture-ishikawa"),
    )

    class RecordingEventProvider:
        async def find_recent_events(self, query, *, now):
            received_event_queries.append(query)
            return ProviderBatch(
                (
                    DisasterEvent(
                        event_id="usgs:venezuela-decoy",
                        hazard=Hazard.EARTHQUAKE,
                        location="Sucre, Venezuela",
                        country=VENEZUELA,
                        event_time=datetime(2026, 8, 5, 18, 0, tzinfo=UTC),
                        source=target_source,
                        magnitude=9.8,
                        significance=6_000,
                    ),
                    DisasterEvent(
                        event_id="usgs:tokyo-decoy",
                        hazard=Hazard.EARTHQUAKE,
                        location="Tokyo, Japan",
                        country=JAPAN,
                        event_time=datetime(2026, 8, 6, 1, 0, tzinfo=UTC),
                        source=target_source,
                        magnitude=9.5,
                        significance=5_000,
                    ),
                    target_event,
                )
            )

    class RecordingSituationProvider:
        async def get_situation_reports(self, event, query, *, now):
            received_situation_queries.append(query)
            source = SourceReference(
                source_id="fixture-situation-reports",
                publisher="FDMA",
                title="Ishikawa impact report",
                canonical_url="https://example.test/fdma-ishikawa",
                published_at=now,
                updated_at=now,
                retrieved_at=now,
            )
            return ProviderBatch(
                (
                    SituationReport(
                        source=source,
                        narrative="Four buildings were damaged in Ishikawa.",
                        facts=(
                            ReportedFact(
                                category="buildings",
                                label="Buildings damaged",
                                value="4",
                                status=FactStatus.CONFIRMED,
                                source=source,
                                event_id=target_event.event_id,
                                claim_id="buildings",
                            ),
                        ),
                        event_id=target_event.event_id,
                    ),
                    SituationReport(
                        source=source,
                        narrative="VENEZUELA-FOREIGN-EVIDENCE-SENTINEL",
                        event_id="usgs:venezuela-decoy",
                    ),
                    SituationReport(
                        source=source,
                        narrative="TOKYO-UNRELATED-EVIDENCE-SENTINEL",
                        event_id="usgs:tokyo-decoy",
                    ),
                )
            )

    model = FailIfCalledModel()
    service = CurrentDisasterReportService(
        RecordingEventProvider(),
        RecordingSituationProvider(),
        clock=lambda: retrieval_time,
    )
    app = create_app(model=model, current_disaster_report=service)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/api/v1/assistant", json={"question": AUGUST_2026_PROMPT}
        )

    assert response.status_code == 200
    body = response.json()
    assert body["response_type"] == "current_disaster"
    assert body["selected_event"]["location"] == "Ishikawa, Japan"
    assert body["selected_event"]["provider_ids"] == [
        "jma:202608051430",
        "usgs:fixture-ishikawa",
    ]
    assert "Buildings damaged: 4" in body["message"]
    assert "VENEZUELA-FOREIGN-EVIDENCE-SENTINEL" not in body["message"]
    assert "TOKYO-UNRELATED-EVIDENCE-SENTINEL" not in body["message"]
    assert len(received_event_queries) == 1
    assert len(received_situation_queries) == 1
    event_query = received_event_queries[0]
    situation_query = received_situation_queries[0]
    assert event_query is situation_query
    assert event_query.hazard == "earthquake"
    assert event_query.country_code == "JPN"
    assert event_query.geography == "Japan"
    assert event_query.date_from == datetime(2026, 8, 4, 15, 0, tzinfo=UTC)
    assert event_query.date_to == datetime(2026, 8, 5, 15, 0, tzinfo=UTC)
    assert model.requests == []


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


@pytest.mark.asyncio
async def test_recognized_unsupported_hazard_returns_coverage_unavailable() -> None:
    model = FakeLanguageModel(error=AssertionError("model must not be called"))
    app = create_app(model=model)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/api/v1/assistant",
            json={"question": "Please give me the latest wildfire in Vietnam."},
        )

    body = response.json()
    assert response.status_code == 200
    assert body["response_type"] == "current_disaster_coverage_unavailable"
    assert body["selected_event"] is None
    assert "wildfire" in body["message"]
    assert "Vietnam" in body["message"]
    assert "No live factual claim" in body["message"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("question", "expected_type", "expected_text"),
    (
        (
            "Give me the latest earthquake information in Thailand.",
            "current_disaster_coverage_unavailable",
            "maintained geographic and source catalog",
        ),
        (
            "Compare the latest earthquakes in Japan and Venezuela.",
            "current_disaster_clarification",
            "one country",
        ),
        (
            "Give me the latest earthquake information.",
            "current_disaster_coverage_unavailable",
            "requested place",
        ),
    ),
)
async def test_unsafe_disaster_ambiguity_never_escapes_to_general_model(
    question: str, expected_type: str, expected_text: str
) -> None:
    model = FakeLanguageModel(error=AssertionError("general model must not be called"))
    app = create_app(model=model)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post("/api/v1/assistant", json={"question": question})

    body = response.json()
    assert response.status_code == 200
    assert body["response_type"] == expected_type
    assert expected_text in body["message"]
    assert model.requests == []
    assert body["investigation"]["actions"] == []


@pytest.mark.asyncio
async def test_general_disaster_knowledge_delegates_without_live_source_claim() -> None:
    model = FakeLanguageModel(response_text="Earthquakes result from fault movement.")
    app = create_app(model=model)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/api/v1/assistant", json={"question": "What causes earthquakes?"}
        )

    assert response.json() == {
        "message": "Earthquakes result from fault movement.",
        "conversation_id": response.json()["conversation_id"],
        "model": "fake-qwen",
    }
    assert len(model.requests) == 1


@pytest.mark.asyncio
async def test_fatality_request_is_focused_and_missing_is_not_zero() -> None:
    model = FakeLanguageModel(error=AssertionError("general model must not be called"))
    app = create_app(
        model=model,
        current_disaster_report=build_current_service(
            fact_category="fatalities",
            fact_label="Fatalities",
            fact_value="2",
        ),
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/api/v1/assistant",
            json={
                "question": (
                    "How many fatalities were reported for the August 5, 2026 "
                    "earthquake in Japan?"
                )
            },
        )

    body = response.json()
    assert "Fatalities: 2" in body["message"]
    assert [section["title"] for section in body["sections"]] == [
        "Focused answer",
        "Event details",
        "Conflicts and uncertainty",
        "Report freshness",
    ]
    assert body["investigation"]["information_needs"] == ["fatalities"]
    assert body["investigation"]["triage_priority"] == "critical"
    assert body["investigation"]["triage_action"] == "escalate_critical"
    assert body["investigation"]["triage_autonomy_mode"] == "human_in_the_loop"
    assert body["investigation"]["triage_requires_human_intervention"] is True
    assert model.requests == []


@pytest.mark.asyncio
async def test_decision_support_request_returns_advisory_evidence_bounded_options() -> (
    None
):
    model = FakeLanguageModel(error=AssertionError("general model must not be called"))
    app = create_app(model=model, current_disaster_report=build_current_service())
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/api/v1/assistant",
            json={
                "question": (
                    "What decision support options should analysts consider for the "
                    "current earthquake in Japan?"
                )
            },
        )

    assert response.status_code == 200
    body = response.json()
    decision_section = next(
        item for item in body["sections"] if item["title"] == "Decision support"
    )
    coordination_section = next(
        item for item in body["sections"] if item["title"] == "Specialist coordination"
    )
    assert "Advisory analytical options only" in decision_section["content"]
    assert "Continue approved-source monitoring" in body["message"]
    assert "Scenario mode:" in decision_section["content"]
    assert "Sensitivity:" in decision_section["content"]
    assert "Evidence gaps:" in decision_section["content"]
    assert "Recommendation layer (" in decision_section["content"]
    assert "Bounded decision state:" in decision_section["content"]
    assert (
        "without changing evidence or safety policy" in coordination_section["content"]
    )
    assert "Supervisor status: autonomous_complete" in coordination_section["content"]
    assert body["investigation"]["information_needs"] == ["decision_support"]
    assert body["investigation"]["decision_action"] in {
        "none",
        "continue_approved_monitoring",
        "compare_verified_updates",
    }
    assert body["investigation"]["decision_autonomy_mode"] in {
        "autonomous_internal",
        "advisory_only",
    }
    assert body["investigation"]["decision_state_revision"] in {0, 1}
    assert isinstance(body["investigation"]["decision_active_internal_states"], list)
    assert body["investigation"]["specialist_handoff_count"] == 2
    assert body["investigation"]["specialist_roles"] == [
        "evidence_reconciliation_specialist",
        "decision_analysis_specialist",
    ]
    assert body["investigation"]["collaboration_status"] == "completed"
    assert body["investigation"]["collaboration_finding_count"] >= 5
    assert body["investigation"]["collaboration_deadlock_count"] == 0
    assert body["investigation"]["collaboration_iterations"] == 1
    assert body["investigation"]["collaboration_fallback_reason"] is None
    assert body["investigation"]["coordination_supervision_id"].startswith(
        "coordination-supervision:"
    )
    assert (
        body["investigation"]["coordination_supervisor_status"] == "autonomous_complete"
    )
    assert body["investigation"]["coordination_sufficient"] is True
    assert body["investigation"]["coordination_missing_finding_keys"] == []
    assert (
        body["investigation"]["coordination_termination_reason"]
        == "sufficient_analytical_end_state"
    )
    assert body["investigation"]["coordination_final_rationale"]
    assert body["investigation"]["coordination_evidence_ids"]
    assert body["decision_support"]["advisory_only"] is True
    assert body["decision_support"]["facts"]
    assert all(
        fact["statement_type"] == "verified_fact"
        for fact in body["decision_support"]["facts"]
    )
    assert body["decision_support"]["estimates"][0]["statement_type"] == "estimate"
    assert body["investigation"]["coordination_analytical_focus"] in {
        "evidence_gaps",
        "material_conflicts",
        "multimodal_review",
        "routine_monitoring",
    }
    assert (
        body["investigation"]["coordination_analytical_parameter_set_id"]
        == "analytical-tuning:v3-governed"
    )
    assert (
        body["investigation"]["coordination_analytical_release_id"]
        == "analytical-tuning-release:v3-governed"
    )
    assert model.requests == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("fact_status", "expected_statement_type"),
    (
        (FactStatus.PRELIMINARY, "preliminary_observation"),
        (FactStatus.ESTIMATED, "source_estimate"),
        (FactStatus.DISPUTED, "disputed_observation"),
    ),
)
async def test_decision_support_api_preserves_uncertain_source_status(
    fact_status: FactStatus,
    expected_statement_type: str,
) -> None:
    model = FakeLanguageModel(error=AssertionError("general model must not be called"))
    app = create_app(
        model=model,
        current_disaster_report=build_current_service(
            fact_category="injuries",
            fact_label="Injuries",
            fact_value="12",
            fact_status=fact_status,
        ),
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/api/v1/assistant",
            json={
                "question": (
                    "What decision support options should analysts consider for the "
                    "current earthquake in Japan?"
                )
            },
        )

    assert response.status_code == 200
    body = response.json()
    source_fact = next(
        fact
        for fact in body["decision_support"]["facts"]
        if fact["status"] == fact_status.value
    )
    estimate = body["decision_support"]["estimates"][0]
    assert source_fact["statement_type"] == expected_statement_type
    assert estimate["statement_type"] == "estimate"
    assert estimate["uncertain_evidence_ids"] == source_fact["evidence_ids"]
    decision_section = next(
        item for item in body["sections"] if item["title"] == "Decision support"
    )
    assert (
        f"[{expected_statement_type}; status={fact_status.value}]"
        in decision_section["content"]
    )
    assert model.requests == []


@pytest.mark.asyncio
async def test_image_request_runs_supported_text_path_and_reports_capability_gap() -> (
    None
):
    model = FakeLanguageModel(error=AssertionError("general model must not be called"))
    app = create_app(model=model, current_disaster_report=build_current_service())
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/api/v1/assistant",
            json={
                "question": (
                    "Show me pictures of the damage from the August 5, 2026 "
                    "Japan earthquake."
                )
            },
        )

    body = response.json()
    assert body["selected_event"]["event_id"] == "jma:fixture-event"
    assert body["investigation"]["output_modalities"] == ["text", "images"]
    assert any(
        "image" in gap.lower() for gap in body["investigation"]["capability_gaps"]
    )
    assert "http" not in " ".join(body["investigation"]["capability_gaps"])
    assert model.requests == []


@pytest.mark.asyncio
async def test_invalid_agent_model_output_uses_default_plan_not_general_model() -> None:
    class BrokenAgentModel:
        calls = 0

        async def interpret(self, question):
            self.calls += 1
            raise ValueError("malformed structured output")

        async def propose_plan(self, task, tool_descriptions):
            self.calls += 1
            raise ValueError("unknown tool")

        async def review_progress(self, task, completed_steps):
            self.calls += 1
            raise ValueError("malformed review")

    agent_model = BrokenAgentModel()
    general = FakeLanguageModel(
        error=AssertionError("general model must not be called")
    )
    app = create_app(
        model=general,
        agent_model=agent_model,
        current_disaster_report=build_current_service(),
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/api/v1/assistant", json={"question": CURRENT_PROMPT}
        )

    body = response.json()
    assert response.status_code == 200
    assert body["selected_event"]["event_id"] == "jma:fixture-event"
    assert len(body["investigation"]["actions"]) == 5
    assert agent_model.calls == 2
    assert general.requests == []
    forbidden = {"reasoning", "prompt", "raw_model_output", "chain_of_thought"}
    assert forbidden.isdisjoint(body["investigation"])


@pytest.mark.asyncio
async def test_operator_image_crosses_real_http_boundary_into_typed_cop() -> None:
    png = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk"
        "+A8AAQUBAScY42YAAAAASUVORK5CYII="
    )

    class FakeVisualAnalyzer:
        calls = 0

        async def analyze(self, request):
            self.calls += 1
            return VisualModelPrediction(
                damage_level=DamageLevel.MAJOR_DAMAGE,
                damage_confidence=0.86,
                damage_cues=("collapsed roof",),
                answer="major structural damage is visible",
                answerable=True,
                answer_confidence=0.81,
                answer_cues=("roof discontinuity",),
                configuration=VisualAnalysisConfiguration(
                    model_id="fake-vlm",
                    model_digest="fixture-digest",
                    adapter_version="fake-adapter-v1",
                    analysis_version="bounded-damage-vqa-v1",
                    prompt_version="dm-visual-analysis-v1",
                    preprocessing_version="original-png-jpeg-bytes-v1",
                    maximum_output_tokens=384,
                    temperature=0,
                    seed=7,
                ),
            )

        async def check_readiness(self):
            return VisualModelReadiness(
                True,
                True,
                "fake-vlm",
                "fixture-digest",
                "fake-adapter-v1",
                "dm-visual-analysis-v1",
                "original-png-jpeg-bytes-v1",
            )

    visual = FakeVisualAnalyzer()
    model = FakeLanguageModel(error=AssertionError("general model must not be called"))
    app = create_app(
        model=model,
        current_disaster_report=build_current_service(),
        visual_analyzer=visual,
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/api/v1/assistant",
            json={
                "question": (
                    "Analyze this image and map visible damage for the August 5, "
                    "2026 earthquake in Japan."
                ),
                "multimodal_assets": [
                    {
                        "content_base64": base64.b64encode(png).decode("ascii"),
                        "attribution": "Licensed operator test fixture",
                        "captured_at": "2026-08-05T11:00:00Z",
                        "footprint": {
                            "crs": "EPSG:4326",
                            "coordinates": [
                                [
                                    [136.8, 36.8],
                                    [137.2, 36.8],
                                    [137.2, 37.2],
                                    [136.8, 37.2],
                                    [136.8, 36.8],
                                ]
                            ],
                        },
                        "declared_hazard": "earthquake",
                        "declared_country_code": "JPN",
                        "capture_role": "post_event",
                        "dataset_id": "http-integration-fixture",
                        "license_name": "fixture-only",
                        "processing_level": "raw",
                    }
                ],
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert visual.calls == 1
    assert body["multimodal"]["evidence_world_state_version"]
    assert body["multimodal"]["observations"][0]["truth_status"] == "analytical"
    assert body["multimodal"]["assets"][0]["source"]["attribution"] == (
        "Licensed operator test fixture"
    )
    assert "content_base64" not in response.text
    cop = body["common_operational_picture"]
    assert cop["multimodal_state_version"] == body["multimodal"]["state_version"]
    feature = cop["layers"][0]["features"][0]
    assert feature["feature_type"] == "analytical"
    assert feature["authority"] == "analytical_generated"
    assert feature["source_asset_ids"] == [body["multimodal"]["assets"][0]["asset_id"]]
    assert feature["visual_observation_ids"]
    assert feature["uncertainty"]
    gaps = body["investigation"]["capability_gaps"]
    assert not any("image" in gap.casefold() for gap in gaps)
    assert not any("map layer" in gap.casefold() for gap in gaps)


@pytest.mark.asyncio
async def test_invalid_inline_image_encoding_is_rejected_before_investigation() -> None:
    model = FakeLanguageModel(error=AssertionError("model must not be called"))
    app = create_app(model=model, current_disaster_report=build_current_service())
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/api/v1/assistant",
            json={
                "question": CURRENT_PROMPT,
                "multimodal_assets": [
                    {
                        "content_base64": "%%%not-base64%%%",
                        "attribution": "Invalid fixture",
                    }
                ],
            },
        )

    assert response.status_code == 422
    assert response.json()["detail"] == (
        "Multimodal asset content must be valid base64."
    )
