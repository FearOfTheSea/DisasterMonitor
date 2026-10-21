from datetime import UTC, datetime
from typing import cast

import pytest

from disaster_monitor.application.earthquake_context import EarthquakeContextService
from disaster_monitor.application.ground_imagery.resolve_region import (
    GroundImageryRegionResolver,
    RegionResolutionState,
)
from disaster_monitor.application.incidents.active_incidents import (
    ActiveIncidentsService,
)
from disaster_monitor.application.incidents.discovery_projection import (
    discovery_incident,
)
from disaster_monitor.application.incidents.imagery_context import (
    ActiveIncidentImageryContextReader,
    EarthquakeProductImageryContextReader,
)
from disaster_monitor.application.incidents.models import (
    ActiveIncident,
    ActiveIncidentsSnapshot,
)
from disaster_monitor.application.ports.ground_imagery.incidents import (
    IncidentImageryContext,
)
from disaster_monitor.domain.disaster import (
    Disaster,
    ProviderTier,
    SourceAuthority,
    SourceReference,
)
from disaster_monitor.domain.discovery import DiscoveryEvent
from disaster_monitor.domain.earthquake_context import EarthquakeContext
from disaster_monitor.domain.events import (
    EventCoordinate,
    EventGeometry,
    EventGeometryKind,
    point_event_geometry,
)
from disaster_monitor.domain.imagery.regions import RegionSourceKind
from disaster_monitor.infrastructure.ground_imagery.geometry import (
    GeodesicGeometryEngine,
)


class StaticImageryContextReader:
    def __init__(self, context: IncidentImageryContext) -> None:
        self._context = context

    async def get_imagery_context(
        self, incident_id: str
    ) -> IncidentImageryContext | None:
        assert incident_id == self._context.incident_id
        return self._context


class RecordingEarthquakeContextService:
    def __init__(self) -> None:
        self.event_ids: list[str] = []

    async def execute(self, event_id: str) -> EarthquakeContext:
        self.event_ids.append(event_id)
        return EarthquakeContext(
            event_id=event_id,
            shakemap_layers=(),
            pager=None,
            ground_failure=(),
            aftershock_forecast=None,
            retrieved_at=datetime(2026, 9, 21, tzinfo=UTC),
        )


def _context(incident_id: str) -> IncidentImageryContext:
    return IncidentImageryContext(
        incident_id=incident_id,
        disaster=Disaster.EARTHQUAKE,
        country_code="FJI",
        event_time=datetime(2026, 9, 21, tzinfo=UTC),
    )


@pytest.mark.asyncio
async def test_gdacs_flood_list_point_is_not_an_imagery_target() -> None:
    now = datetime(2026, 9, 21, tzinfo=UTC)
    source = SourceReference(
        source_id="gdacs-floods",
        publisher="GDACS",
        title="Flood in Japan",
        canonical_url="https://www.gdacs.org/report.aspx?eventid=1104140&eventtype=FL",
        published_at=None,
        updated_at=None,
        retrieved_at=now,
        authority=SourceAuthority.SECONDARY,
    )
    incident = ActiveIncident(
        event_id="gdacs:fl:1104140",
        disaster=Disaster.FLOOD,
        country=None,
        location="Japan",
        event_time=now,
        geometry=point_event_geometry(41.2928, 141.1835, source),
        measurements=(),
        provider_ids=("gdacs:fl:1104140",),
        provider_tier=ProviderTier.SECONDARY,
        source_authority=SourceAuthority.SECONDARY,
        source=source,
    )

    class StaticIncidents:
        async def lookup(self, identifier: str) -> ActiveIncident:
            assert identifier == incident.event_id
            return incident

        async def execute(self, query: object) -> ActiveIncidentsSnapshot:
            return ActiveIncidentsSnapshot(now, (incident,), (), ())

    reader = ActiveIncidentImageryContextReader(
        cast(ActiveIncidentsService, StaticIncidents())
    )
    context = await reader.get_imagery_context(incident.event_id)

    assert context is not None
    assert context.verified_point is None
    assert context.reported_places == ("Japan",)
    region = await GroundImageryRegionResolver(GeodesicGeometryEngine()).resolve_async(
        context
    )
    assert region.state is RegionResolutionState.NEEDS_REGION


@pytest.mark.asyncio
async def test_non_usgs_incident_does_not_request_usgs_products() -> None:
    context = _context("emsc:20260921_0000133")
    service = RecordingEarthquakeContextService()
    reader = EarthquakeProductImageryContextReader(
        StaticImageryContextReader(context), cast(EarthquakeContextService, service)
    )

    result = await reader.get_imagery_context(context.incident_id)

    assert result is context
    assert service.event_ids == []


@pytest.mark.asyncio
async def test_canonical_usgs_incident_requests_usgs_products() -> None:
    context = _context("usgs:us7000test")
    service = RecordingEarthquakeContextService()
    reader = EarthquakeProductImageryContextReader(
        StaticImageryContextReader(context), cast(EarthquakeContextService, service)
    )

    result = await reader.get_imagery_context(context.incident_id)

    assert result is context
    assert service.event_ids == [context.incident_id]


async def test_reported_discovery_area_is_context_not_a_damage_perimeter():
    now = datetime(2026, 10, 18, tzinfo=UTC)
    source = SourceReference(
        "news", "Daily", "Drought area", "https://daily.example/area", now, None, now
    )
    geometry = EventGeometry(
        EventGeometryKind.AREA,
        source,
        coordinates=tuple(
            EventCoordinate(lat, lon)
            for lat, lon in ((10, 100), (10, 101), (11, 101), (10, 100))
        ),
    )
    event = DiscoveryEvent(
        "discovery:area",
        Disaster.DROUGHT,
        "Reported province",
        now,
        geometry,
        (),
        0,
        supplemental_sources=(source,),
    )
    incident = discovery_incident(
        event, now, scan_id="11111111-1111-4111-8111-111111111111"
    )

    class Incidents:
        async def lookup(self, identifier):
            return incident

    context = await ActiveIncidentImageryContextReader(
        cast(ActiveIncidentsService, Incidents())
    ).get_imagery_context(event.event_id)
    assert context.evidence[0].source.source_kind is RegionSourceKind.REPORTED_PLACE
    assert context.evidence[0].source.reference == source.canonical_url
    assert "not a measured damage" in context.evidence[0].semantic_role


async def test_mention_day_onset_is_expanded_without_inventing_exact_midnight():
    from disaster_monitor.domain.discovery import (
        DiscoveryArticle,
        ReportingInterval,
        assess_article,
        group_reports,
    )

    now = datetime(2026, 10, 18, 12, tzinfo=UTC)
    source = SourceReference(
        "news",
        "Daily",
        "Earthquake in Riverton",
        "https://daily.example/quake",
        now,
        None,
        now,
    )
    article = DiscoveryArticle(
        source, "An earthquake struck Riverton on 9 October 2026."
    )
    event = group_reports(
        (assess_article(article, ReportingInterval.at_start(7, now)),)
    )[0]
    incident = discovery_incident(
        event, now, scan_id="11111111-1111-4111-8111-111111111111"
    )

    class Incidents:
        async def lookup(self, identifier):
            return incident

    context = await ActiveIncidentImageryContextReader(
        cast(ActiveIncidentsService, Incidents())
    ).get_imagery_context(event.event_id)
    assert context.onset.precision == "date_only_unknown_timezone"
    assert context.onset.earliest < event.event_time < context.onset.latest


async def test_unknown_discovery_onset_never_targets_imagery_using_publication():
    from disaster_monitor.domain.discovery import (
        DiscoveryArticle,
        ReportingInterval,
        assess_article,
        group_reports,
    )

    now = datetime(2026, 10, 18, 23, 9, 50, tzinfo=UTC)
    source = SourceReference(
        "news", "Daily", "Floods", "https://daily.example/flood", now, None, now
    )
    event = group_reports(
        (
            assess_article(
                DiscoveryArticle(source, "Floods hit Riverton in early October."),
                ReportingInterval.at_start(30, now),
            ),
        )
    )[0]
    assert event.event_time is None
    assert event.reports[0].mention.time.wording == "early October"
    incident = discovery_incident(
        event, now, scan_id="11111111-1111-4111-8111-111111111111"
    )

    class Incidents:
        async def lookup(self, identifier):
            return incident

    context = await ActiveIncidentImageryContextReader(
        cast(ActiveIncidentsService, Incidents())
    ).get_imagery_context(incident.event_id)
    assert context is None
