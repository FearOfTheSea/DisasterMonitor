import base64
from datetime import UTC, datetime
from hashlib import sha256

import httpx
import pytest
from assistant_http_fixtures import (
    AUGUST_2026_PROMPT,
    CURRENT_PROMPT,
    JAPAN,
    NOW,
    VENEZUELA,
    build_current_service,
    injected_capabilities,
)
from conftest import FakeLanguageModel

from disaster_monitor.application.disaster import (
    DisasterQuery,
    GeographicScope,
    ProviderBatch,
    WorldwideDisasterEvent,
)
from disaster_monitor.application.dto import ModelRequest
from disaster_monitor.application.media import (
    DisasterMediaGallery,
    DisasterMediaItem,
    MediaAssociationStatus,
    MediaContentRole,
    MediaCreditKind,
    MediaRightsStatus,
    StoredMediaAsset,
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
    Disaster,
    DisasterEvent,
    EventMeasurement,
    FactStatus,
    MeasurementKind,
    ReportedFact,
    SituationReport,
    SourceAuthority,
    SourceReference,
    point_event_geometry,
)
from disaster_monitor.infrastructure.composition import build_current_disaster_report
from disaster_monitor.infrastructure.configuration import Settings
from disaster_monitor.infrastructure.geography.static_country_catalog import (
    StaticCountryCatalog,
)
from disaster_monitor.main import create_app


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
                        disaster=Disaster.EARTHQUAKE,
                        location="South Pacific Ocean",
                        event_time=now,
                        source=source,
                        geometry=point_event_geometry(-20.0, -170.0, source),
                        measurements=(
                            EventMeasurement(
                                MeasurementKind.MAGNITUDE, 6.4, source=source
                            ),
                            EventMeasurement(
                                MeasurementKind.DEPTH,
                                18.0,
                                "km",
                                source=source,
                            ),
                        ),
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
                        disasters=frozenset({Disaster.EARTHQUAKE}),
                        country_codes=None,
                        geographic_scopes=frozenset({GeographicScope.WORLDWIDE}),
                        event_scopes=frozenset({GeographicScope.WORLDWIDE}),
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
    assert body["selected_event"]["geography_status"] == "worldwide"
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
            assert context.event_id == "global-catalog:fixture-event"
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
                        "media.association.disaster_text",
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
    assert body["media_gallery"]["event_id"] == "global-catalog:fixture-event"
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
        publisher="Global Catalog",
        title="Ishikawa target event",
        canonical_url="https://example.test/global-catalog-ishikawa",
        published_at=target_time,
        updated_at=target_time,
        retrieved_at=retrieval_time,
    )
    target_event = DisasterEvent(
        event_id="global-catalog:202608051430",
        disaster=Disaster.EARTHQUAKE,
        location="Ishikawa, Japan",
        country=JAPAN,
        event_time=target_time,
        source=target_source,
        geometry=point_event_geometry(37.0, 137.0, target_source),
        measurements=(
            EventMeasurement(MeasurementKind.MAGNITUDE, 6.1, source=target_source),
            EventMeasurement(
                MeasurementKind.INTENSITY, "Global Catalog 6-", source=target_source
            ),
        ),
        provider_ids=("global-catalog:202608051430", "usgs:fixture-ishikawa"),
    )

    class RecordingEventProvider:
        async def find_recent_events(self, query, *, now):
            received_event_queries.append(query)
            return ProviderBatch(
                (
                    DisasterEvent(
                        event_id="usgs:venezuela-decoy",
                        disaster=Disaster.EARTHQUAKE,
                        location="Sucre, Venezuela",
                        country=VENEZUELA,
                        event_time=datetime(2026, 8, 5, 18, 0, tzinfo=UTC),
                        source=target_source,
                        measurements=(
                            EventMeasurement(
                                MeasurementKind.MAGNITUDE, 9.8, source=target_source
                            ),
                            EventMeasurement(
                                MeasurementKind.PROVIDER_SIGNIFICANCE,
                                6_000,
                                source=target_source,
                            ),
                        ),
                    ),
                    DisasterEvent(
                        event_id="usgs:tokyo-decoy",
                        disaster=Disaster.EARTHQUAKE,
                        location="Tokyo, Japan",
                        country=JAPAN,
                        event_time=datetime(2026, 8, 6, 1, 0, tzinfo=UTC),
                        source=target_source,
                        measurements=(
                            EventMeasurement(
                                MeasurementKind.MAGNITUDE, 9.5, source=target_source
                            ),
                            EventMeasurement(
                                MeasurementKind.PROVIDER_SIGNIFICANCE,
                                5_000,
                                source=target_source,
                            ),
                        ),
                    ),
                    target_event,
                )
            )

    class RecordingSituationProvider:
        async def get_situation_reports(self, event, query, *, now):
            received_situation_queries.append(query)
            source = SourceReference(
                source_id="fixture-situation-reports",
                publisher="Global Situation",
                title="Ishikawa impact report",
                canonical_url="https://example.test/global-situation-ishikawa",
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
        provider_capabilities=injected_capabilities(),
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
        "global-catalog:202608051430",
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
    assert event_query.disaster == "earthquake"
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
            EmptyEventProvider(),
            EmptySituationProvider(),
            provider_capabilities=injected_capabilities(),
            clock=lambda: NOW,
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
async def test_recognized_wildfire_has_a_source_backed_event_path() -> None:
    service = build_current_disaster_report(Settings(_env_file=None))
    try:
        country = StaticCountryCatalog().get_by_alpha3("VNM")
        assert country is not None
        selection = service.provider_registry.select(
            DisasterQuery(Disaster.WILDFIRE, country, "recent", ()),
            ProviderRole.EVENT_DISCOVERY,
        )
        assert [(item.name, item.source_id) for item in selection.registrations] == [
            ("NASA EONET Wildfires", "nasa-eonet-wildfires"),
            ("GDACS wildfires", "gdacs-wildfires"),
        ]
    finally:
        await service.aclose()


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
        "operator_actions": [],
    }
    assert len(model.requests) == 1
