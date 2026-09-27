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
from disaster_monitor.domain.earthquake_context import EarthquakeContext
from disaster_monitor.domain.events import point_event_geometry
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
