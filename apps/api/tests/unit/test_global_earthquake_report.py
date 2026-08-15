from datetime import UTC, datetime, timedelta

import pytest

from disaster_monitor.application.disaster import (
    GlobalDisasterEvent,
    GlobalEarthquakeQuery,
    GlobalEventSelection,
    ProviderBatch,
)
from disaster_monitor.application.services.global_earthquake_report import (
    GlobalEarthquakeReportService,
)
from disaster_monitor.application.services.provider_registry import (
    ProviderCapabilities,
    ProviderRegistration,
    ProviderRole,
)
from disaster_monitor.domain.disaster import (
    Hazard,
    SourceAuthority,
    SourceReference,
)

NOW = datetime(2026, 8, 15, 8, tzinfo=UTC)


def _event(
    event_id: str, *, event_time: datetime, magnitude: float, host: str = "usgs.test"
) -> GlobalDisasterEvent:
    source = SourceReference(
        source_id="usgs-earthquakes",
        publisher="United States Geological Survey",
        title=f"Event {event_id}",
        canonical_url=f"https://{host}/{event_id}",
        published_at=event_time,
        updated_at=event_time,
        retrieved_at=NOW,
        authority=SourceAuthority.SCIENTIFIC_AUTHORITY,
    )
    return GlobalDisasterEvent(
        event_id=f"usgs:{event_id}",
        hazard=Hazard.EARTHQUAKE,
        location=f"Location {event_id}",
        event_time=event_time,
        source=source,
        latitude=10.0,
        longitude=20.0,
        magnitude=magnitude,
        depth_km=12.0,
        significance=magnitude * 100,
        provider_ids=(f"usgs:{event_id}",),
    )


class FakeGlobalProvider:
    source_id = "usgs-earthquakes"
    allowed_hosts = frozenset({"usgs.test"})

    def __init__(self, records: tuple[GlobalDisasterEvent, ...]) -> None:
        self.records = records
        self.queries: list[GlobalEarthquakeQuery] = []

    async def find_global_earthquakes(self, query, *, now):
        self.queries.append(query)
        return ProviderBatch(self.records)


def _service(records: tuple[GlobalDisasterEvent, ...]) -> GlobalEarthquakeReportService:
    provider = FakeGlobalProvider(records)
    return GlobalEarthquakeReportService(
        ProviderRegistration(
            "USGS",
            provider,
            ProviderCapabilities(
                roles=frozenset({ProviderRole.EVENT_DISCOVERY}),
                hazards=frozenset({Hazard.EARTHQUAKE}),
                country_codes=None,
            ),
            source_id=provider.source_id,
            allowed_hosts=provider.allowed_hosts,
        ),
        clock=lambda: NOW,
    )


@pytest.mark.asyncio
async def test_worldwide_report_selects_latest_or_strongest_deterministically() -> None:
    older_stronger = _event(
        "older-stronger", event_time=NOW - timedelta(hours=2), magnitude=7.0
    )
    newer = _event("newer", event_time=NOW - timedelta(hours=1), magnitude=5.0)
    service = _service((older_stronger, newer))

    latest = await service.execute(GlobalEarthquakeQuery())
    strongest = await service.execute(
        GlobalEarthquakeQuery(selection=GlobalEventSelection.STRONGEST)
    )

    assert latest.response_type == "current_disaster_global_earthquake"
    assert latest.selected_event is not None
    assert latest.selected_event.event_id == "usgs:newer"
    assert strongest.selected_event is not None
    assert strongest.selected_event.event_id == "usgs:older-stronger"
    assert latest.partial
    assert "does not claim globally complete" in latest.message


@pytest.mark.asyncio
async def test_worldwide_report_fails_closed_for_unapproved_source_host() -> None:
    invalid = _event("invalid", event_time=NOW, magnitude=6.0, host="evil.test")

    report = await _service((invalid,)).execute(GlobalEarthquakeQuery())

    assert report.response_type == "current_disaster_global_verification_failed"
    assert report.selected_event is None
    assert any("source policy" in warning for warning in report.warnings)
