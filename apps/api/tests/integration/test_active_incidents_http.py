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
        },
        "measurements": [],
        "provider_ids": ["fixture:fire-1"],
        "provider_tier": "primary",
        "source_authority": "scientific_authority",
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
    assert body["warnings"] == ["Fixture provider returned a partial response."]


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
