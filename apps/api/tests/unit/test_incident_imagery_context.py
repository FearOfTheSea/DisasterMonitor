from datetime import UTC, datetime
from typing import cast

import pytest

from disaster_monitor.application.earthquake_context import EarthquakeContextService
from disaster_monitor.application.incidents.imagery_context import (
    EarthquakeProductImageryContextReader,
)
from disaster_monitor.application.ports.ground_imagery.incidents import (
    IncidentImageryContext,
)
from disaster_monitor.domain.disaster import Disaster
from disaster_monitor.domain.earthquake_context import EarthquakeContext


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
