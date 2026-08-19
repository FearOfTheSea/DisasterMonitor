from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from disaster_monitor.application.disaster import (
    GeographicScope,
    ProviderBatch,
    WorldwideDisasterEvent,
    WorldwideDisasterQuery,
    WorldwideSelectionIntent,
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
    Disaster,
    EventMeasurement,
    MeasurementKind,
    SourceAuthority,
    SourceReference,
    point_event_geometry,
)

NOW = datetime(2026, 8, 15, 8, tzinfo=UTC)


def _event(
    event_id: str, *, event_time: datetime, magnitude: float, host: str = "usgs.test"
) -> WorldwideDisasterEvent:
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
    return WorldwideDisasterEvent(
        event_id=f"usgs:{event_id}",
        disaster=Disaster.EARTHQUAKE,
        location=f"Location {event_id}",
        event_time=event_time,
        source=source,
        geometry=point_event_geometry(10.0, 20.0, source),
        measurements=(
            EventMeasurement(MeasurementKind.MAGNITUDE, magnitude, source=source),
            EventMeasurement(MeasurementKind.DEPTH, 12.0, "km", source=source),
            EventMeasurement(
                MeasurementKind.PROVIDER_SIGNIFICANCE,
                magnitude * 100,
                source=source,
            ),
        ),
        provider_ids=(f"usgs:{event_id}",),
    )


class FakeGlobalProvider:
    source_id = "usgs-earthquakes"
    allowed_hosts = frozenset({"usgs.test"})

    def __init__(self, records: tuple[WorldwideDisasterEvent, ...]) -> None:
        self.records = records
        self.queries: list[WorldwideDisasterQuery] = []

    async def find_worldwide_events(self, query, *, now):
        self.queries.append(query)
        return ProviderBatch(self.records)

    async def find_recent_events(self, query, *, now):
        return ProviderBatch()


class RecencyBoundedGlobalProvider(FakeGlobalProvider):
    async def find_worldwide_events(self, query, *, now):
        self.queries.append(query)
        if query.selection_intent is WorldwideSelectionIntent.STRONGEST:
            return ProviderBatch((self.records[0],))
        return ProviderBatch((self.records[-1],))


def _service(
    records: tuple[WorldwideDisasterEvent, ...],
    provider_type: type[FakeGlobalProvider] = FakeGlobalProvider,
) -> WorldwideDisasterReportService:
    provider = provider_type(records)
    return WorldwideDisasterReportService(
        ProviderRegistry(
            (
                ProviderRegistration(
                    "USGS",
                    provider,
                    ProviderCapabilities(
                        roles=frozenset({ProviderRole.EVENT_DISCOVERY}),
                        disasters=frozenset({records[0].disaster}),
                        country_codes=None,
                        geographic_scopes=frozenset({GeographicScope.WORLDWIDE}),
                        event_scopes=frozenset({GeographicScope.WORLDWIDE}),
                    ),
                    source_id=provider.source_id,
                    allowed_hosts=provider.allowed_hosts,
                    event_provider=provider,
                    worldwide_provider=provider,
                ),
            )
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

    latest = await service.execute(WorldwideDisasterQuery(Disaster.EARTHQUAKE))
    strongest = await service.execute(
        WorldwideDisasterQuery(
            Disaster.EARTHQUAKE,
            selection_intent=WorldwideSelectionIntent.STRONGEST,
        ),
    )

    assert latest.response_type == "current_disaster_global_earthquake"
    assert latest.selected_event is not None
    assert latest.selected_event.event_id == "usgs:newer"
    assert strongest.selected_event is not None
    assert strongest.selected_event.event_id == "usgs:older-stronger"
    assert latest.partial
    assert "does not establish complete global impact" in latest.message


@pytest.mark.asyncio
async def test_strongest_query_requests_a_non_recent_bounded_dataset() -> None:
    older_stronger = _event(
        "older-stronger", event_time=NOW - timedelta(days=10), magnitude=8.0
    )
    newer = _event("newer", event_time=NOW, magnitude=5.0)
    service = _service((older_stronger, newer), RecencyBoundedGlobalProvider)

    report = await service.execute(
        WorldwideDisasterQuery(
            Disaster.EARTHQUAKE,
            selection_intent=WorldwideSelectionIntent.STRONGEST,
        )
    )

    assert report.selected_event is not None
    assert report.selected_event.event_id == "usgs:older-stronger"


@pytest.mark.asyncio
async def test_multiple_worldwide_providers_are_aggregated_deterministically() -> None:
    older = _event("older", event_time=NOW - timedelta(hours=2), magnitude=5.0)
    newer = _event("newer", event_time=NOW - timedelta(hours=1), magnitude=4.0)
    provider = FakeGlobalProvider((older, newer))
    capabilities = ProviderCapabilities(
        roles=frozenset({ProviderRole.EVENT_DISCOVERY}),
        disasters=frozenset({Disaster.EARTHQUAKE}),
        country_codes=None,
        geographic_scopes=frozenset({GeographicScope.WORLDWIDE}),
        event_scopes=frozenset({GeographicScope.WORLDWIDE}),
    )
    registry = ProviderRegistry(
        tuple(
            ProviderRegistration(
                name,
                provider,
                capabilities,
                source_id=provider.source_id,
                allowed_hosts=provider.allowed_hosts,
                worldwide_provider=provider,
            )
            for name in ("USGS primary", "USGS mirror")
        )
    )

    report = await WorldwideDisasterReportService(registry, clock=lambda: NOW).execute(
        WorldwideDisasterQuery(Disaster.EARTHQUAKE)
    )

    assert len(provider.queries) == 2
    assert report.selected_event is not None
    assert report.selected_event.event_id == "usgs:newer"


@pytest.mark.asyncio
async def test_worldwide_report_fails_closed_for_unapproved_source_host() -> None:
    invalid = _event("invalid", event_time=NOW, magnitude=6.0, host="evil.test")

    report = await _service((invalid,)).execute(
        WorldwideDisasterQuery(Disaster.EARTHQUAKE)
    )

    assert report.response_type == "current_disaster_worldwide_verification_failed"
    assert report.selected_event is None
    assert any("source policy" in warning for warning in report.warnings)


@pytest.mark.asyncio
async def test_worldwide_non_earthquake_event_needs_no_earthquake_measurements() -> (
    None
):
    flood = replace(
        _event("flood", event_time=NOW, magnitude=5.0),
        disaster=Disaster.FLOOD,
        geometry=None,
        measurements=(),
    )

    report = await _service((flood,)).execute(WorldwideDisasterQuery(Disaster.FLOOD))

    assert report.response_type == "current_disaster_worldwide"
    assert report.selected_event is not None
    assert report.selected_event.event_id == flood.event_id
    assert report.selected_event.disaster is Disaster.FLOOD
