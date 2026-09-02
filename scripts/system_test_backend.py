"""Deterministic FastAPI server used by the Playwright system test."""

import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import uvicorn

api_src = Path(__file__).resolve().parents[1] / "apps" / "api" / "src"
sys.path.insert(0, str(api_src))

from disaster_monitor.application.disaster import (
    GeographicScope,
    ProviderBatch,
    ProviderIssue,
    WorldwideDisasterEvent,
)
from disaster_monitor.application.agent.operator_actions import OPERATOR_ACTION_IDS
from disaster_monitor.application.dto import (
    ModelReadiness,
    ModelRequest,
    ModelResponse,
    ModelToolCall,
)
from disaster_monitor.application.services.active_incidents import (
    ActiveIncidentsService,
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
from disaster_monitor.domain.disaster import (
    Disaster,
    DisasterEvent,
    EventCoordinate,
    EventGeometry,
    EventGeometryKind,
    EventMeasurement,
    FactStatus,
    MeasurementKind,
    ProviderTier,
    ReportedFact,
    SituationReport,
    SourceAuthority,
    SourceReference,
    point_event_geometry,
)
from disaster_monitor.infrastructure.geography.static_country_catalog import (
    StaticCountryCatalog,
)
from disaster_monitor.infrastructure.llm.structured_agent_model import (
    StructuredAgentModel,
)
from disaster_monitor.main import create_app

NOW = datetime(2026, 8, 6, 3, 0, tzinfo=UTC)
TARGET_TIME = datetime(2026, 8, 5, 14, 30, tzinfo=UTC)
FOREIGN_SENTINEL = "VENEZUELA-FOREIGN-EVIDENCE-SENTINEL"
UNRELATED_SENTINEL = "TOKYO-UNRELATED-EVIDENCE-SENTINEL"
MODEL_SENTINEL = "GENERAL-MODEL-SENTINEL"
CATALOG = StaticCountryCatalog()
JAPAN = CATALOG.get_by_alpha3("JPN")
VENEZUELA = CATALOG.get_by_alpha3("VEN")
assert JAPAN is not None and VENEZUELA is not None


class FakeSystemModel:
    async def generate(self, request: ModelRequest):
        if any(tool.name == "fit_country" for tool in request.tools):
            return ModelResponse(
                text="",
                model="fake-qwen",
                tool_calls=(ModelToolCall("fit_country", {"country_code": "JPN"}),),
            )
        prompt = request.messages[-1].content.casefold()
        if "latest flood in japan" in prompt:
            return ModelResponse(
                text=json.dumps(
                    {
                        "task_kind": "investigation",
                        "disaster": "flood",
                        "country_code": "JPN",
                        "country_name": "Japan",
                        "geographic_scope": "country",
                        "place_mentions": ["Japan"],
                        "current_or_event_specific": True,
                        "date_from": None,
                        "date_to": None,
                        "information_needs": ["event_overview"],
                        "output_modalities": ["text"],
                        "event_discriminators": [],
                        "requested_response_language": "en",
                        "response_language_explicit": False,
                        "worldwide_selection": None,
                        "clarification_question": None,
                        "operator_action_ids": [
                            "time:24h",
                            "create-watch:3600",
                        ],
                    }
                ),
                model="fake-qwen",
            )
        raise AssertionError(f"{MODEL_SENTINEL}: source-backed request reached model")

    async def check_readiness(self) -> ModelReadiness:
        return ModelReadiness(True, True, "fake-qwen")


class FakeSystemEventProvider:
    async def find_recent_events(self, _query, *, now):
        if _query.disaster is Disaster.FLOOD:
            source = SourceReference(
                source_id="system-flood-events",
                publisher="Deterministic flood fixture",
                title="Hokkaido flood fixture event",
                canonical_url="https://example.test/system-flood-event",
                published_at=now - timedelta(minutes=30),
                updated_at=now - timedelta(minutes=10),
                retrieved_at=now,
                authority=SourceAuthority.NATIONAL_AUTHORITY,
            )
            return ProviderBatch(
                (
                    DisasterEvent(
                        event_id="system:flood-japan",
                        disaster=Disaster.FLOOD,
                        location="Hokkaido flood fixture",
                        country=JAPAN,
                        event_time=now - timedelta(minutes=30),
                        source=source,
                        geometry=point_event_geometry(43.0, 141.0, source),
                        measurements=(
                            EventMeasurement(
                                MeasurementKind.SEVERITY,
                                "high",
                                source=source,
                            ),
                        ),
                        provider_ids=("system:flood-japan",),
                    ),
                )
            )
        usgs_history_source = SourceReference(
            source_id="system-usgs-events",
            publisher="USGS fixture",
            title="Deterministic USGS Japan earthquake history event",
            canonical_url="https://example.test/system-usgs-history-event",
            published_at=TARGET_TIME,
            updated_at=now - timedelta(minutes=10),
            retrieved_at=now,
        )
        usgs_source = SourceReference(
            source_id="system-usgs-events",
            publisher="USGS fixture",
            title="Deterministic USGS Japan earthquake event",
            canonical_url="https://example.test/system-usgs-event",
            published_at=TARGET_TIME,
            updated_at=now - timedelta(minutes=5),
            retrieved_at=now,
        )
        unrelated_source = SourceReference(
            source_id="system-usgs-events",
            publisher="USGS fixture",
            title="Unrelated Tokyo earthquake event",
            canonical_url="https://example.test/system-unrelated-event",
            published_at=datetime(2026, 8, 5, 23, 15, tzinfo=UTC),
            updated_at=now - timedelta(minutes=5),
            retrieved_at=now,
        )
        foreign_source = SourceReference(
            source_id="system-usgs-events",
            publisher="USGS fixture",
            title="More significant Venezuela earthquake event",
            canonical_url="https://example.test/system-venezuela-event",
            published_at=datetime(2026, 8, 6, 1, 45, tzinfo=UTC),
            updated_at=now - timedelta(minutes=1),
            retrieved_at=now,
        )
        return ProviderBatch(
            (
                DisasterEvent(
                    event_id="usgs:history-system-fixture",
                    disaster=Disaster.EARTHQUAKE,
                    location="Ishikawa, Japan",
                    country=JAPAN,
                    event_time=TARGET_TIME,
                    source=usgs_history_source,
                    geometry=point_event_geometry(37.0, 137.0, usgs_history_source),
                    measurements=(
                        EventMeasurement(
                            MeasurementKind.MAGNITUDE, 6.0, source=usgs_history_source
                        ),
                        EventMeasurement(
                            MeasurementKind.INTENSITY,
                            "USGS intensity 6-",
                            source=usgs_history_source,
                        ),
                        EventMeasurement(
                            MeasurementKind.DEPTH, 12, "km", source=usgs_history_source
                        ),
                        EventMeasurement(
                            MeasurementKind.PROVIDER_SIGNIFICANCE,
                            400,
                            source=usgs_history_source,
                        ),
                    ),
                    provider_ids=("usgs:history-system-fixture",),
                ),
                DisasterEvent(
                    event_id="usgs:system-fixture",
                    disaster=Disaster.EARTHQUAKE,
                    location="Ishikawa, Japan",
                    country=JAPAN,
                    event_time=TARGET_TIME + timedelta(seconds=20),
                    source=usgs_source,
                    geometry=point_event_geometry(37.02, 137.01, usgs_source),
                    measurements=(
                        EventMeasurement(
                            MeasurementKind.MAGNITUDE, 6.1, source=usgs_source
                        ),
                        EventMeasurement(
                            MeasurementKind.DEPTH, 11, "km", source=usgs_source
                        ),
                        EventMeasurement(
                            MeasurementKind.PROVIDER_SIGNIFICANCE,
                            600,
                            source=usgs_source,
                        ),
                    ),
                    provider_ids=("usgs:system-fixture",),
                ),
                DisasterEvent(
                    event_id="usgs:unrelated",
                    disaster=Disaster.EARTHQUAKE,
                    location="Tokyo, Japan",
                    country=JAPAN,
                    event_time=datetime(2026, 8, 5, 23, 15, tzinfo=UTC),
                    source=unrelated_source,
                    geometry=point_event_geometry(35.7, 139.7, unrelated_source),
                    measurements=(
                        EventMeasurement(
                            MeasurementKind.MAGNITUDE, 9.5, source=unrelated_source
                        ),
                        EventMeasurement(
                            MeasurementKind.PROVIDER_SIGNIFICANCE,
                            5_000,
                            source=unrelated_source,
                        ),
                    ),
                    provider_ids=("usgs:unrelated",),
                ),
                DisasterEvent(
                    event_id="usgs:venezuela-decoy",
                    disaster=Disaster.EARTHQUAKE,
                    location="Sucre, Venezuela",
                    country=VENEZUELA,
                    event_time=datetime(2026, 8, 6, 1, 45, tzinfo=UTC),
                    source=foreign_source,
                    geometry=point_event_geometry(10.4, -63.5, foreign_source),
                    measurements=(
                        EventMeasurement(
                            MeasurementKind.MAGNITUDE, 9.8, source=foreign_source
                        ),
                        EventMeasurement(
                            MeasurementKind.PROVIDER_SIGNIFICANCE,
                            6_000,
                            source=foreign_source,
                        ),
                    ),
                    provider_ids=("usgs:venezuela-decoy",),
                ),
            )
        )


class FakeSystemSituationProvider:
    async def get_situation_reports(self, event, _query, *, now):
        if event.disaster is Disaster.FLOOD:
            source = SourceReference(
                source_id="system-flood-situation",
                publisher="Deterministic flood situation fixture",
                title="Hokkaido flood fixture situation update",
                canonical_url="https://example.test/system-flood-situation",
                published_at=now - timedelta(minutes=20),
                updated_at=now - timedelta(minutes=5),
                retrieved_at=now,
                authority=SourceAuthority.NATIONAL_AUTHORITY,
            )
            return ProviderBatch(
                (
                    SituationReport(
                        source=source,
                        narrative=(
                            "The controlled Hokkaido flood fixture reports a bounded "
                            "source-backed situation update."
                        ),
                        event_id=event.event_id,
                        disaster=Disaster.FLOOD,
                    ),
                )
            )
        source = SourceReference(
            source_id="system-situation-reports",
            publisher="Global situation fixture",
            title="Deterministic situation update",
            canonical_url="https://example.test/system-situation",
            published_at=now - timedelta(minutes=5),
            updated_at=now - timedelta(minutes=2),
            retrieved_at=now,
        )

        return ProviderBatch(
            (
                SituationReport(
                    source=source,
                    narrative=(
                        "Four buildings were damaged in Ishikawa; an airport closure "
                        "was reported while officials inspected the area."
                    ),
                    facts=(
                        ReportedFact(
                            category="buildings",
                            label="Buildings damaged",
                            value="4",
                            status=FactStatus.CONFIRMED,
                            source=source,
                            event_id=event.event_id,
                            claim_id="buildings",
                        ),
                        ReportedFact(
                            category="fatalities",
                            label="Fatalities",
                            value="2",
                            status=FactStatus.CONFIRMED,
                            source=source,
                            event_id=event.event_id,
                            claim_id="fatalities",
                        ),
                    ),
                    event_id=event.event_id,
                ),
                SituationReport(
                    source=source,
                    narrative="Tokyo suffered unrelated damage after another quake.",
                    event_id="usgs:unrelated",
                ),
                SituationReport(
                    source=SourceReference(
                        source_id="system-foreign-reports",
                        publisher="Foreign fixture",
                        title="Venezuela decoy update",
                        canonical_url="https://example.test/system-venezuela-situation",
                        published_at=now - timedelta(minutes=3),
                        updated_at=now - timedelta(minutes=1),
                        retrieved_at=now,
                    ),
                    narrative=f"{FOREIGN_SENTINEL}: foreign impacts were reported.",
                    event_id="usgs:venezuela-decoy",
                    countries=("Venezuela",),
                ),
                SituationReport(
                    source=source,
                    narrative=f"{UNRELATED_SENTINEL}: unrelated Japan event damage.",
                    event_id="usgs:unrelated",
                    countries=("Japan",),
                ),
            )
        )


class FakeSystemWorldwideProvider:
    source_id = "system-active-incidents"
    allowed_hosts = frozenset({"example.test"})

    async def find_worldwide_events(self, query, *, now):
        event_id, location, age = {
            Disaster.EARTHQUAKE: (
                "system-active-earthquake",
                "Aleutian earthquake fixture",
                timedelta(minutes=30),
            ),
            Disaster.FLOOD: (
                "system-active-flood",
                "Lower Mekong flood fixture",
                timedelta(minutes=40),
            ),
            Disaster.WILDFIRE: (
                "system-active-wildfire",
                "Equatorial wildfire perimeter fixture",
                timedelta(minutes=50),
            ),
            Disaster.LANDSLIDE: (
                "system-active-landslide",
                "Taiwan landslide fixture",
                timedelta(minutes=60),
            ),
            Disaster.TROPICAL_CYCLONE: (
                "system-active-tropical-cyclone",
                "Western Pacific cyclone track fixture",
                timedelta(minutes=70),
            ),
            Disaster.VOLCANIC_ERUPTION: (
                "system-active-volcanic-eruption",
                "East African volcanic eruption fixture",
                timedelta(minutes=80),
            ),
        }[query.disaster]
        source = SourceReference(
            source_id=self.source_id,
            publisher="Deterministic six-hazard fixture",
            title=f"{location} source record",
            canonical_url=f"https://example.test/{event_id}",
            published_at=now - age,
            updated_at=now - timedelta(minutes=20),
            retrieved_at=now,
            authority=SourceAuthority.SCIENTIFIC_AUTHORITY,
        )
        geometry = {
            Disaster.EARTHQUAKE: point_event_geometry(52.0, -170.0, source),
            Disaster.FLOOD: point_event_geometry(
                15.0,
                105.0,
                source,
                estimated=True,
            ),
            Disaster.WILDFIRE: EventGeometry(
                kind=EventGeometryKind.AREA,
                source=source,
                coordinates=(
                    EventCoordinate(-1.0, -121.0),
                    EventCoordinate(1.0, -121.0),
                    EventCoordinate(1.0, -119.0),
                    EventCoordinate(-1.0, -119.0),
                    EventCoordinate(-1.0, -121.0),
                ),
            ),
            Disaster.LANDSLIDE: point_event_geometry(23.5, 121.0, source),
            Disaster.TROPICAL_CYCLONE: EventGeometry(
                kind=EventGeometryKind.TRACK,
                source=source,
                coordinates=(
                    EventCoordinate(20.0, 145.0),
                    EventCoordinate(20.0, 155.0),
                ),
            ),
            Disaster.VOLCANIC_ERUPTION: point_event_geometry(-3.0, 36.0, source),
        }[query.disaster]
        return ProviderBatch(
            (
                WorldwideDisasterEvent(
                    event_id=event_id,
                    disaster=query.disaster,
                    location=location,
                    event_time=now - age,
                    source=source,
                    geometry=geometry,
                    provider_ids=(f"system:{event_id}",),
                ),
            ),
            issues=(
                ProviderIssue(
                    "Deterministic six-hazard fixture",
                    "Flood fixture coverage is intentionally degraded.",
                    reason_code="partial_fixture",
                ),
            )
            if query.disaster is Disaster.FLOOD
            else (),
        )


def build_system_active_incidents_service() -> ActiveIncidentsService:
    provider = FakeSystemWorldwideProvider()
    registry = ProviderRegistry(
        (
            ProviderRegistration(
                "Deterministic six-hazard fixture",
                provider,
                ProviderCapabilities(
                    roles=frozenset({ProviderRole.EVENT_DISCOVERY}),
                    disasters=frozenset(Disaster),
                    country_codes=None,
                    geographic_scopes=frozenset({GeographicScope.WORLDWIDE}),
                    event_scopes=frozenset({GeographicScope.WORLDWIDE}),
                ),
                tier=ProviderTier.PRIMARY,
                source_id=provider.source_id,
                allowed_hosts=provider.allowed_hosts,
                worldwide_provider=provider,
            ),
        )
    )
    return ActiveIncidentsService(registry, clock=lambda: NOW)


if __name__ == "__main__":
    fake_model = FakeSystemModel()
    uvicorn.run(
        create_app(
            model=fake_model,
            agent_model=StructuredAgentModel(
                fake_model,
                operator_action_ids=tuple(sorted(OPERATOR_ACTION_IDS)),
            ),
            current_disaster_report=CurrentDisasterReportService(
                FakeSystemEventProvider(),
                FakeSystemSituationProvider(),
                provider_capabilities=(
                    ProviderCapabilities(
                        frozenset({ProviderRole.EVENT_DISCOVERY}),
                        frozenset({Disaster.EARTHQUAKE, Disaster.FLOOD}),
                        None,
                    ),
                    ProviderCapabilities(
                        frozenset({ProviderRole.SITUATION_EVIDENCE}),
                        frozenset({Disaster.EARTHQUAKE, Disaster.FLOOD}),
                        None,
                    ),
                ),
            ),
            active_incidents_service=build_system_active_incidents_service(),
        ),
        host="127.0.0.1",
        port=8787,
        log_level="warning",
    )
