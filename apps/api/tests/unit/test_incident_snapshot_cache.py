"""Browsing reuses acquisitions while retaining immutable pagination."""

import asyncio
from datetime import timedelta

import pytest

from disaster_monitor.application.disaster import ProviderBatch
from disaster_monitor.application.incidents.models import ActiveIncidentsQuery
from disaster_monitor.application.sources.provider_registry import ProviderRegistry
from disaster_monitor.domain.disaster import Disaster

from .active_incidents_support import (
    NOW,
    FakeWorldwideProvider,
    _active_incidents_service,
    _event,
    _registration,
)


def _service(clock=lambda: NOW):
    provider = FakeWorldwideProvider(
        "quake-source",
        ProviderBatch(
            tuple(
                _event("quake-source", Disaster.EARTHQUAKE, f"quake-{index}", NOW)
                for index in range(3)
            )
        ),
    )
    return _active_incidents_service(
        ProviderRegistry((_registration("Quakes", provider, Disaster.EARTHQUAKE),)),
        clock=clock,
    ), provider


@pytest.mark.asyncio
async def test_filters_and_concurrent_reads_share_one_acquisition() -> None:
    service, provider = _service()
    await asyncio.gather(service.execute(), service.execute())
    filtered = await service.execute(ActiveIncidentsQuery(search="quake-1"))
    assert [incident.event_id for incident in filtered.incidents] == ["quake-1"]
    assert len(provider.queries) == 1


@pytest.mark.asyncio
async def test_cursor_survives_more_than_eight_other_refreshes() -> None:
    current = [NOW]
    service, _ = _service(lambda: current[0])
    first = await service.execute(ActiveIncidentsQuery(page_size=1))
    for index in range(10):
        current[0] = NOW + timedelta(seconds=index + 1)
        await service.refresh()
    next_page = await service.execute(
        ActiveIncidentsQuery(page_size=1, cursor=first.next_cursor)
    )
    assert len(next_page.incidents) == 1
    assert next_page.snapshot_version == first.snapshot_version


@pytest.mark.asyncio
async def test_drought_does_not_fetch_other_hazards() -> None:
    service, provider = _service()
    result = await service.execute(ActiveIncidentsQuery(hazard=Disaster.DROUGHT))
    assert result.incidents == ()
    assert provider.queries == []


@pytest.mark.asyncio
async def test_provider_alias_lookup_ignores_page_and_filters() -> None:
    service, _ = _service()
    await service.execute(ActiveIncidentsQuery(page_size=1, search="quake-0"))
    selected = await service.lookup("quake-source:quake-2")
    assert selected.event_id == "quake-2"


@pytest.mark.asyncio
async def test_refresh_failure_retains_previous_hazard_rows_and_marks_stale():
    service, provider = _service()
    first = await service.execute()
    provider.result = RuntimeError("upstream unavailable")
    second = await service.refresh()
    assert second.incidents == first.incidents
    assert second.is_stale
    assert second.refresh_state == "stale"
    quake = next(row for row in second.coverage if row.disaster is Disaster.EARTHQUAKE)
    assert quake.incident_count == len(first.incidents)


@pytest.mark.asyncio
async def test_cursor_expiry_is_explicit_after_thirty_minutes():
    from disaster_monitor.application.incidents.snapshot_cache import (
        IncidentCursorExpiredError,
    )

    current = [NOW]
    service, _ = _service(lambda: current[0])
    first = await service.execute(ActiveIncidentsQuery(page_size=1))
    current[0] += timedelta(minutes=31)
    with pytest.raises(IncidentCursorExpiredError):
        await service.execute(
            ActiveIncidentsQuery(page_size=1, cursor=first.next_cursor)
        )


async def test_provider_failure_after_cursor_expiry_retains_last_current_rows():
    current = [NOW]
    service, provider = _service(lambda: current[0])
    first = await service.execute()
    current[0] += timedelta(minutes=31)
    provider.result = RuntimeError("provider outage")
    second = await service.refresh()
    assert second.incidents == first.incidents
    assert second.is_stale
