from dataclasses import replace
from datetime import timedelta

import pytest

from disaster_monitor.application.disaster import ProviderBatch
from disaster_monitor.application.incidents.active_incidents import (
    ActiveIncidentsQuery,
    ActiveIncidentsService,
    IncidentView,
)
from disaster_monitor.application.sources.provider_registry import ProviderRegistry
from disaster_monitor.domain.disaster import Disaster, IncidentActivityStatus
from disaster_monitor.infrastructure.geography.static_country_catalog import (
    StaticCountryCatalog,
)

from .active_incidents_support import (
    NOW,
    FakeWorldwideProvider,
    _event,
    _registration,
)


def _service(provider: FakeWorldwideProvider) -> ActiveIncidentsService:
    return ActiveIncidentsService(
        ProviderRegistry(
            (_registration("View source", provider, Disaster.EARTHQUAKE),)
        ),
        country_catalog=StaticCountryCatalog(),
        clock=lambda: NOW,
    )


@pytest.mark.asyncio
async def test_lifecycle_views_keep_onset_and_update_time_separate() -> None:
    ongoing_old = _event(
        "view-source",
        Disaster.EARTHQUAKE,
        "ongoing-old",
        NOW - timedelta(days=12),
        activity_status=IncidentActivityStatus.ONGOING,
    )
    updated_old = replace(
        _event(
            "view-source",
            Disaster.EARTHQUAKE,
            "updated-old",
            NOW - timedelta(days=12),
        ),
        source=replace(
            ongoing_old.source,
            updated_at=NOW - timedelta(days=1),
        ),
    )
    updated_old = replace(
        updated_old,
        geometry=(
            replace(updated_old.geometry, source=updated_old.source)
            if updated_old.geometry is not None
            else None
        ),
    )
    recent = _event(
        "view-source",
        Disaster.EARTHQUAKE,
        "recent",
        NOW - timedelta(hours=2),
    )
    service = _service(
        FakeWorldwideProvider(
            "view-source", ProviderBatch((ongoing_old, updated_old, recent))
        )
    )

    recent_result = await service.execute(
        ActiveIncidentsQuery(time_window_days=7, view=IncidentView.RECENT)
    )
    ongoing_result = await service.execute(
        ActiveIncidentsQuery(time_window_days=7, view=IncidentView.ONGOING)
    )
    updated_result = await service.execute(
        ActiveIncidentsQuery(time_window_days=7, view=IncidentView.RECENTLY_UPDATED)
    )

    assert [item.event_id for item in recent_result.incidents] == ["recent"]
    assert [item.event_id for item in ongoing_result.incidents] == ["ongoing-old"]
    assert [item.event_id for item in updated_result.incidents] == [
        "recent",
        "updated-old",
    ]


@pytest.mark.asyncio
async def test_cursor_pagination_is_bound_to_one_snapshot_and_query() -> None:
    events = tuple(
        _event(
            "view-source",
            Disaster.EARTHQUAKE,
            f"quake-{index}",
            NOW - timedelta(hours=index),
        )
        for index in range(3)
    )
    service = _service(FakeWorldwideProvider("view-source", ProviderBatch(events)))
    first = await service.execute(ActiveIncidentsQuery(page_size=2))

    assert first.has_more is True
    assert first.next_cursor is not None
    second = await service.execute(
        ActiveIncidentsQuery(page_size=2, cursor=first.next_cursor)
    )

    assert second.snapshot_version == first.snapshot_version
    assert [item.event_id for item in second.incidents] == ["quake-2"]
    assert second.has_more is False
    with pytest.raises(ValueError, match="does not match"):
        await service.execute(
            ActiveIncidentsQuery(
                page_size=2,
                cursor=first.next_cursor,
                search="different query",
            )
        )


@pytest.mark.asyncio
async def test_filters_search_complete_inventory_before_three_row_pages() -> None:
    events = tuple(
        _event(
            "view-source",
            Disaster.EARTHQUAKE,
            f"quake-{index:02d}",
            NOW - timedelta(hours=index),
        )
        for index in range(25)
    )
    service = _service(FakeWorldwideProvider("view-source", ProviderBatch(events)))

    first = await service.execute(ActiveIncidentsQuery(page_size=3))
    collected = list(first.incidents)
    cursor = first.next_cursor
    while cursor is not None:
        page = await service.execute(ActiveIncidentsQuery(page_size=3, cursor=cursor))
        collected.extend(page.incidents)
        cursor = page.next_cursor

    assert len(collected) == 25
    assert len({item.event_id for item in collected}) == 25
    assert first.total_incident_count == 25

    matching = await service.execute(
        ActiveIncidentsQuery(page_size=3, search="quake-24")
    )
    assert [item.event_id for item in matching.incidents] == ["quake-24"]
    assert matching.has_more is False
