from datetime import UTC, datetime

import httpx
import pytest

from disaster_monitor.application.disaster import ProviderBatch
from disaster_monitor.application.services.active_incidents import (
    ActiveIncident,
    ActiveIncidentsQuery,
    ActiveIncidentsSnapshot,
    DisasterIncidentCoverage,
    IncidentCoverageState,
)
from disaster_monitor.application.services.current_disaster_report import (
    CurrentDisasterReportService,
)
from disaster_monitor.application.services.event_policies import (
    ASSOCIATION_LIMITATION,
    CompoundHazardCorrelation,
    CompoundHazardRelationship,
)
from disaster_monitor.application.services.provider_registry import (
    ProviderCapabilities,
    ProviderRole,
)
from disaster_monitor.domain.disaster import (
    Disaster,
    EventCoordinate,
    EventGeometry,
    EventGeometryKind,
    ProviderTier,
    SourceAuthority,
    SourceReference,
)
from disaster_monitor.main import create_app

NOW = datetime(2026, 8, 20, 6, tzinfo=UTC)


class FakeLanguageModel:
    async def generate(self, request):
        raise AssertionError("The incidents endpoint must not use the language model.")

    async def check_readiness(self):
        raise AssertionError("Readiness is outside this test.")


class EmptyEventProvider:
    async def find_recent_events(self, query, *, now):
        return ProviderBatch()


class EmptySituationProvider:
    async def get_situation_reports(self, event, query, *, now):
        return ProviderBatch()


def _current_service() -> CurrentDisasterReportService:
    return CurrentDisasterReportService(
        EmptyEventProvider(),
        EmptySituationProvider(),
        provider_capabilities=(
            ProviderCapabilities(
                roles=frozenset({ProviderRole.EVENT_DISCOVERY}),
                disasters=frozenset(Disaster),
                country_codes=None,
            ),
            ProviderCapabilities(
                roles=frozenset({ProviderRole.SITUATION_EVIDENCE}),
                disasters=frozenset(Disaster),
                country_codes=None,
            ),
        ),
        clock=lambda: NOW,
    )


def _snapshot() -> ActiveIncidentsSnapshot:
    source = SourceReference(
        source_id="fixture-wildfires",
        publisher="Fixture Fire Authority",
        title="Fixture wildfire perimeter",
        canonical_url="https://wildfires.example/incidents/fire-1",
        published_at=datetime(2026, 8, 20, 4, tzinfo=UTC),
        updated_at=datetime(2026, 8, 20, 5, tzinfo=UTC),
        retrieved_at=NOW,
        authority=SourceAuthority.SCIENTIFIC_AUTHORITY,
        snapshot_id="snapshot:fire-1",
    )
    incident = ActiveIncident(
        event_id="fire-1",
        disaster=Disaster.WILDFIRE,
        location="Fixture reserve",
        event_time=datetime(2026, 8, 20, 3, tzinfo=UTC),
        geometry=EventGeometry(
            kind=EventGeometryKind.AREA,
            source=source,
            coordinates=(
                EventCoordinate(10.0, 20.0),
                EventCoordinate(11.0, 21.0),
                EventCoordinate(10.0, 22.0),
            ),
        ),
        measurements=(),
        provider_ids=("fixture:fire-1",),
        provider_tier=ProviderTier.PRIMARY,
        source_authority=SourceAuthority.SCIENTIFIC_AUTHORITY,
        source=source,
    )
    coverage = tuple(
        DisasterIncidentCoverage(
            disaster=disaster,
            state=(
                IncidentCoverageState.EVENTS_FOUND
                if disaster is Disaster.WILDFIRE
                else IncidentCoverageState.NO_MATCHING_RECORDS
            ),
            incident_count=1 if disaster is Disaster.WILDFIRE else 0,
            providers=("Fixture provider",),
            detail="Fixture coverage detail.",
        )
        for disaster in Disaster
    )
    return ActiveIncidentsSnapshot(
        retrieved_at=NOW,
        incidents=(incident,),
        coverage=coverage,
        warnings=("Fixture provider returned a partial response.",),
    )


class RecordingActiveIncidentsService:
    def __init__(self) -> None:
        self.queries: list[ActiveIncidentsQuery] = []

    async def execute(self, query: ActiveIncidentsQuery | None = None):
        self.queries.append(query or ActiveIncidentsQuery())
        return _snapshot()


@pytest.mark.asyncio
async def test_active_incidents_response_preserves_typed_source_evidence() -> None:
    service = RecordingActiveIncidentsService()
    app = create_app(
        model=FakeLanguageModel(),
        current_disaster_report=_current_service(),
        active_incidents_service=service,  # type: ignore[arg-type]
    )

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get(
            "/api/v1/incidents?time_window_days=5&limit_per_disaster=4"
        )

    assert response.status_code == 200
    assert service.queries == [ActiveIncidentsQuery(5, 4)]
    body = response.json()
    assert body["retrieved_at"] == "2026-08-20T06:00:00Z"
    assert len(body["coverage"]) == len(Disaster)
    assert body["coverage"][2] == {
        "disaster": "wildfire",
        "state": "events_found",
        "incident_count": 1,
        "providers": ["Fixture provider"],
        "detail": "Fixture coverage detail.",
    }
    assert body["incidents"][0] == {
        "event_id": "fire-1",
        "disaster": "wildfire",
        "location": "Fixture reserve",
        "event_time": "2026-08-20T03:00:00Z",
        "geometry": {
            "kind": "area",
            "coordinates": [
                {"latitude": 10.0, "longitude": 20.0},
                {"latitude": 11.0, "longitude": 21.0},
                {"latitude": 10.0, "longitude": 22.0},
            ],
            "description": None,
            "source_id": "fixture-wildfires",
            "estimated": False,
        },
        "measurements": [],
        "provider_ids": ["fixture:fire-1"],
        "provider_tier": "primary",
        "source_authority": "scientific_authority",
        "physical_event_id": None,
        "source": {
            "source_id": "fixture-wildfires",
            "publisher": "Fixture Fire Authority",
            "title": "Fixture wildfire perimeter",
            "canonical_url": "https://wildfires.example/incidents/fire-1",
            "published_at": "2026-08-20T04:00:00Z",
            "updated_at": "2026-08-20T05:00:00Z",
            "retrieved_at": "2026-08-20T06:00:00Z",
            "snapshot_id": "snapshot:fire-1",
        },
    }
    assert body["correlations"] == []
    assert body["warnings"] == ["Fixture provider returned a partial response."]


@pytest.mark.asyncio
async def test_active_incidents_serializes_resolvable_compound_correlations() -> None:
    source = _snapshot().incidents[0].source
    first = ActiveIncident(
        event_id="quake-1",
        disaster=Disaster.EARTHQUAKE,
        location="Fixture coast",
        event_time=NOW,
        geometry=None,
        measurements=(),
        provider_ids=("fixture:quake-1",),
        provider_tier=ProviderTier.SECONDARY,
        source_authority=source.authority,
        source=source,
        physical_event_id="physical-event:quake-1",
    )
    second = ActiveIncident(
        event_id="slide-1",
        disaster=Disaster.LANDSLIDE,
        location="Fixture slope",
        event_time=NOW,
        geometry=None,
        measurements=(),
        provider_ids=("fixture:slide-1",),
        provider_tier=ProviderTier.SECONDARY,
        source_authority=source.authority,
        source=source,
    )
    correlation = CompoundHazardCorrelation(
        correlation_id="compound-correlation:v1:fixture",
        rule_id="compound-hazard:earthquake-landslide:v1",
        relationship=CompoundHazardRelationship.SPATIOTEMPORAL_ASSOCIATION,
        first_event_id=first.event_id,
        first_physical_event_id=first.physical_event_id,
        first_disaster=first.disaster,
        second_event_id=second.event_id,
        second_physical_event_id=None,
        second_disaster=second.disaster,
        distance_km=42.5,
        time_delta_seconds=7200,
        source_ids=(source.source_id,),
        summary=(
            "Earthquake quake-1 and landslide slide-1 are approximately "
            "42.5 km and 2 hours apart."
        ),
    )
    base = _snapshot()
    correlated_snapshot = ActiveIncidentsSnapshot(
        retrieved_at=base.retrieved_at,
        incidents=(first, second),
        coverage=base.coverage,
        warnings=(),
        correlations=(correlation,),
    )

    class CorrelatedService:
        async def execute(self, query=None):
            return correlated_snapshot

    app = create_app(
        model=FakeLanguageModel(),
        current_disaster_report=_current_service(),
        active_incidents_service=CorrelatedService(),  # type: ignore[arg-type]
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/api/v1/incidents")

    assert response.status_code == 200
    body = response.json()
    incident_ids = {item["event_id"] for item in body["incidents"]}
    item = body["correlations"][0]
    assert {item["first_event_id"], item["second_event_id"]} <= incident_ids
    assert item == {
        "correlation_id": "compound-correlation:v1:fixture",
        "rule_id": "compound-hazard:earthquake-landslide:v1",
        "relationship": "spatiotemporal_association",
        "first_event_id": "quake-1",
        "first_physical_event_id": "physical-event:quake-1",
        "first_disaster": "earthquake",
        "second_event_id": "slide-1",
        "second_physical_event_id": None,
        "second_disaster": "landslide",
        "distance_km": 42.5,
        "time_delta_seconds": 7200,
        "source_ids": ["fixture-wildfires"],
        "summary": correlation.summary,
        "limitation": ASSOCIATION_LIMITATION,
    }


@pytest.mark.asyncio
async def test_active_incidents_http_query_bounds_are_validated() -> None:
    service = RecordingActiveIncidentsService()
    app = create_app(
        model=FakeLanguageModel(),
        current_disaster_report=_current_service(),
        active_incidents_service=service,  # type: ignore[arg-type]
    )

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        default_response = await client.get("/api/v1/incidents")
        invalid_responses = [
            await client.get(f"/api/v1/incidents?{parameter}={value}")
            for parameter, value in (
                ("time_window_days", 0),
                ("time_window_days", 31),
                ("limit_per_disaster", 0),
                ("limit_per_disaster", 21),
            )
        ]

    assert default_response.status_code == 200
    assert service.queries == [ActiveIncidentsQuery()]
    assert [response.status_code for response in invalid_responses] == [422] * 4
