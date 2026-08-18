from datetime import UTC, datetime

import pytest

from disaster_monitor.application.agent.task_normalization import (
    deterministic_task_draft,
    validate_disaster_task,
    worldwide_disaster_query,
)
from disaster_monitor.application.disaster import (
    DisasterQuery,
    GeographicScope,
    ProviderBatch,
    WorldwideDisasterEvent,
    WorldwideDisasterQuery,
)
from disaster_monitor.application.services.disaster_query_parser import (
    DisasterQueryParser,
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
    EventGeographyStatus,
    EventMeasurement,
    Hazard,
    MeasurementKind,
    SourceAuthority,
    SourceReference,
    point_event_geometry,
)
from disaster_monitor.infrastructure.composition import build_current_disaster_report
from disaster_monitor.infrastructure.configuration import Settings
from disaster_monitor.infrastructure.geography.static_country_catalog import (
    StaticCountryCatalog,
)

NOW = datetime(2026, 8, 18, 12, tzinfo=UTC)


def test_latest_worldwide_tropical_cyclone_uses_existing_worldwide_query_path() -> None:
    question = "What is the latest tropical cyclone worldwide?"

    query = worldwide_disaster_query(question)
    assert query == WorldwideDisasterQuery(Hazard.TROPICAL_CYCLONE)

    catalog = StaticCountryCatalog()
    task = validate_disaster_task(
        question,
        deterministic_task_draft(question),
        country_catalog=catalog,
        query_parser=DisasterQueryParser(catalog),
    )
    assert task.geographic_scope is GeographicScope.WORLDWIDE
    assert task.country is None
    assert task.query is None
    assert task.worldwide_query == query


def test_composition_registers_only_gdacs_for_worldwide_tropical_cyclones() -> None:
    service = build_current_disaster_report(Settings())

    worldwide = service.provider_registry.select(
        WorldwideDisasterQuery(Hazard.TROPICAL_CYCLONE),
        ProviderRole.EVENT_DISCOVERY,
    )
    assert [registration.name for registration in worldwide.registrations] == [
        "GDACS tropical cyclones"
    ]
    registration = worldwide.registrations[0]
    assert registration.capabilities.roles == frozenset({ProviderRole.EVENT_DISCOVERY})
    assert registration.capabilities.hazards == frozenset({Hazard.TROPICAL_CYCLONE})
    assert registration.capabilities.country_codes is None
    assert registration.capabilities.geographic_scopes == frozenset(
        {GeographicScope.WORLDWIDE}
    )
    assert registration.capabilities.event_scopes == frozenset(
        {GeographicScope.WORLDWIDE}
    )
    assert registration.event_provider is None
    assert registration.situation_provider is None
    assert registration.worldwide_situation_provider is None
    assert service.source_catalog.get("gdacs-tropical-cyclones") is not None


def test_country_tropical_cyclone_queries_do_not_select_worldwide_gdacs() -> None:
    service = build_current_disaster_report(Settings())
    vietnam = StaticCountryCatalog().get_by_alpha3("VNM")
    assert vietnam is not None

    country_query = DisasterQuery(
        Hazard.TROPICAL_CYCLONE,
        vietnam,
        "recent",
        ("latest",),
    )
    selection = service.provider_registry.select(
        country_query, ProviderRole.EVENT_DISCOVERY
    )

    assert [registration.name for registration in selection.registrations] == [
        "NCHMF Vietnam warnings"
    ]


class GdacsFixtureProvider:
    source_id = "gdacs-tropical-cyclones"
    allowed_hosts = frozenset({"www.gdacs.org"})

    def __init__(self, events: tuple[WorldwideDisasterEvent, ...]) -> None:
        self.events = events
        self.queries: list[WorldwideDisasterQuery] = []

    async def find_worldwide_events(self, query, *, now):
        self.queries.append(query)
        return ProviderBatch(self.events)


def _event(event_id: str, event_time: datetime) -> WorldwideDisasterEvent:
    source = SourceReference(
        source_id="gdacs-tropical-cyclones",
        publisher="Global Disaster Alert and Coordination System (GDACS)",
        title="GDACS tropical cyclone event",
        canonical_url=(
            "https://www.gdacs.org/gdacsapi/api/events/geteventdata?"
            f"eventtype=TC&eventid={event_id}"
        ),
        published_at=None,
        updated_at=event_time,
        retrieved_at=NOW,
        authority=SourceAuthority.SCIENTIFIC_AUTHORITY,
    )
    return WorldwideDisasterEvent(
        event_id=f"gdacs:tc:{event_id}",
        hazard=Hazard.TROPICAL_CYCLONE,
        location="Worldwide cyclone source location",
        event_time=event_time,
        source=source,
        geometry=point_event_geometry(20.0, 150.0, source),
        measurements=(
            EventMeasurement(MeasurementKind.SEVERITY, "Green", source=source),
        ),
        provider_ids=(f"gdacs:tc:{event_id}",),
    )


@pytest.mark.asyncio
async def test_worldwide_report_selects_latest_gdacs_event_and_is_partial() -> None:
    provider = GdacsFixtureProvider(
        (
            _event("1001301", datetime(2026, 8, 15, 21, tzinfo=UTC)),
            _event("1001303", datetime(2026, 8, 18, 9, tzinfo=UTC)),
        )
    )
    registry = ProviderRegistry(
        (
            ProviderRegistration(
                "GDACS tropical cyclones",
                provider,
                ProviderCapabilities(
                    roles=frozenset({ProviderRole.EVENT_DISCOVERY}),
                    hazards=frozenset({Hazard.TROPICAL_CYCLONE}),
                    country_codes=None,
                    geographic_scopes=frozenset({GeographicScope.WORLDWIDE}),
                    event_scopes=frozenset({GeographicScope.WORLDWIDE}),
                ),
                source_id="gdacs-tropical-cyclones",
                allowed_hosts=frozenset({"www.gdacs.org"}),
                worldwide_provider=provider,
            ),
        )
    )

    report = await WorldwideDisasterReportService(registry, clock=lambda: NOW).execute(
        WorldwideDisasterQuery(Hazard.TROPICAL_CYCLONE)
    )

    assert report.selected_event is not None
    assert report.selected_event.event_id == "gdacs:tc:1001303"
    assert report.selected_event.geography_status is EventGeographyStatus.WORLDWIDE
    assert report.partial
    assert report.capability_gaps == (
        "No worldwide situation-evidence capability is configured.",
    )
    assert report.termination_reason == "partial_worldwide_event_evidence"
    assert provider.queries == [WorldwideDisasterQuery(Hazard.TROPICAL_CYCLONE)]
