from datetime import UTC, datetime, timedelta

import pytest

from disaster_monitor.application.disaster import (
    GeographicScope,
    ProviderBatch,
    ProviderIssue,
    WorldwideDisasterEvent,
)
from disaster_monitor.application.services.active_incidents import (
    ActiveIncidentsQuery,
    ActiveIncidentsService,
    IncidentCoverageState,
)
from disaster_monitor.application.services.provider_registry import (
    ProviderCapabilities,
    ProviderRegistration,
    ProviderRegistry,
    ProviderRole,
)
from disaster_monitor.domain.disaster import (
    Disaster,
    ProviderTier,
    SourceAuthority,
    SourceReference,
    descriptive_event_geometry,
    point_event_geometry,
)

NOW = datetime(2026, 8, 20, 6, tzinfo=UTC)


class FakeWorldwideProvider:
    def __init__(
        self,
        source_id: str,
        result: ProviderBatch[WorldwideDisasterEvent] | Exception,
    ) -> None:
        self.source_id = source_id
        self.allowed_hosts = frozenset({f"{source_id}.example"})
        self.result = result
        self.queries = []

    async def find_worldwide_events(self, query, *, now):
        self.queries.append((query, now))
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def _source(
    source_id: str,
    event_time: datetime,
    *,
    authority: SourceAuthority = SourceAuthority.SCIENTIFIC_AUTHORITY,
) -> SourceReference:
    return SourceReference(
        source_id=source_id,
        publisher=f"{source_id} publisher",
        title=f"{source_id} bulletin",
        canonical_url=f"https://{source_id}.example/events",
        published_at=event_time,
        updated_at=event_time + timedelta(minutes=5),
        retrieved_at=NOW,
        authority=authority,
    )


def _event(
    source_id: str,
    disaster: Disaster,
    event_id: str,
    event_time: datetime,
    *,
    descriptive: bool = False,
) -> WorldwideDisasterEvent:
    source = _source(source_id, event_time)
    geometry = (
        descriptive_event_geometry("Provider supplied location text", source)
        if descriptive
        else point_event_geometry(10.5, 20.25, source)
    )
    return WorldwideDisasterEvent(
        event_id=event_id,
        disaster=disaster,
        location=f"{disaster.value} location",
        event_time=event_time,
        source=source,
        geometry=geometry,
        provider_ids=(f"{source_id}:{event_id}",),
    )


def _registration(
    name: str,
    provider: FakeWorldwideProvider,
    disaster: Disaster,
    *,
    tier: ProviderTier = ProviderTier.SECONDARY,
    configured: bool = True,
) -> ProviderRegistration:
    return ProviderRegistration(
        name,
        provider,
        ProviderCapabilities(
            roles=frozenset({ProviderRole.EVENT_DISCOVERY}),
            disasters=frozenset({disaster}),
            country_codes=None,
            requires_configuration=not configured,
            geographic_scopes=frozenset({GeographicScope.WORLDWIDE}),
            event_scopes=frozenset({GeographicScope.WORLDWIDE}),
        ),
        tier=tier,
        source_id=provider.source_id,
        configured=configured,
        allowed_hosts=provider.allowed_hosts,
        worldwide_provider=provider,
    )


def _coverage(snapshot):
    return {item.disaster: item for item in snapshot.coverage}


@pytest.mark.asyncio
async def test_aggregates_supported_disasters_and_orders_newest_then_identity() -> None:
    earthquake = FakeWorldwideProvider(
        "earthquake-source",
        ProviderBatch(
            (
                _event(
                    "earthquake-source",
                    Disaster.EARTHQUAKE,
                    "quake-z",
                    NOW - timedelta(hours=1),
                ),
                _event(
                    "earthquake-source",
                    Disaster.EARTHQUAKE,
                    "quake-a",
                    NOW - timedelta(hours=1),
                ),
            )
        ),
    )
    flood = FakeWorldwideProvider(
        "flood-source",
        ProviderBatch(
            (
                _event(
                    "flood-source",
                    Disaster.FLOOD,
                    "flood-new",
                    NOW,
                ),
            )
        ),
    )
    service = ActiveIncidentsService(
        ProviderRegistry(
            (
                _registration("Earthquakes", earthquake, Disaster.EARTHQUAKE),
                _registration("Floods", flood, Disaster.FLOOD),
            )
        ),
        clock=lambda: NOW,
    )

    snapshot = await service.execute()

    assert [item.event_id for item in snapshot.incidents] == [
        "flood-new",
        "quake-a",
        "quake-z",
    ]
    assert len(snapshot.coverage) == len(Disaster)
    assert _coverage(snapshot)[Disaster.EARTHQUAKE].state is (
        IncidentCoverageState.EVENTS_FOUND
    )
    assert _coverage(snapshot)[Disaster.FLOOD].state is (
        IncidentCoverageState.EVENTS_FOUND
    )
    assert _coverage(snapshot)[Disaster.WILDFIRE].state is (
        IncidentCoverageState.UNAVAILABLE
    )
    assert snapshot.retrieved_at == NOW


@pytest.mark.asyncio
async def test_usable_primary_records_suppress_lower_tier_records() -> None:
    primary = FakeWorldwideProvider(
        "primary-floods",
        ProviderBatch((_event("primary-floods", Disaster.FLOOD, "primary", NOW),)),
    )
    secondary = FakeWorldwideProvider(
        "secondary-floods",
        ProviderBatch(
            (
                _event(
                    "secondary-floods",
                    Disaster.FLOOD,
                    "secondary",
                    NOW + timedelta(hours=1),
                ),
            )
        ),
    )
    service = ActiveIncidentsService(
        ProviderRegistry(
            (
                _registration(
                    "Secondary floods",
                    secondary,
                    Disaster.FLOOD,
                    tier=ProviderTier.SECONDARY,
                ),
                _registration(
                    "Primary floods",
                    primary,
                    Disaster.FLOOD,
                    tier=ProviderTier.PRIMARY,
                ),
            )
        ),
        clock=lambda: NOW,
    )

    snapshot = await service.execute()

    assert [item.event_id for item in snapshot.incidents] == ["primary"]
    assert snapshot.incidents[0].provider_tier is ProviderTier.PRIMARY


@pytest.mark.asyncio
async def test_secondary_records_are_fallback_after_empty_primary() -> None:
    primary = FakeWorldwideProvider(
        "primary-floods",
        ProviderBatch(
            issues=(
                ProviderIssue(
                    "Primary floods",
                    "Primary floods returned no matching records.",
                    reason_code="empty_result",
                ),
            )
        ),
    )
    secondary = FakeWorldwideProvider(
        "secondary-floods",
        ProviderBatch((_event("secondary-floods", Disaster.FLOOD, "fallback", NOW),)),
    )
    service = ActiveIncidentsService(
        ProviderRegistry(
            (
                _registration(
                    "Primary floods",
                    primary,
                    Disaster.FLOOD,
                    tier=ProviderTier.PRIMARY,
                ),
                _registration(
                    "Secondary floods",
                    secondary,
                    Disaster.FLOOD,
                    tier=ProviderTier.SECONDARY,
                ),
            )
        ),
        clock=lambda: NOW,
    )

    snapshot = await service.execute()

    assert [item.event_id for item in snapshot.incidents] == ["fallback"]
    assert snapshot.incidents[0].provider_tier is ProviderTier.SECONDARY
    assert _coverage(snapshot)[Disaster.FLOOD].state is (
        IncidentCoverageState.EVENTS_FOUND
    )


@pytest.mark.asyncio
async def test_provider_failure_degrades_only_affected_coverage() -> None:
    failed = FakeWorldwideProvider("failed-floods", RuntimeError("secret failure"))
    earthquake = FakeWorldwideProvider(
        "earthquake-source",
        ProviderBatch(
            (_event("earthquake-source", Disaster.EARTHQUAKE, "quake", NOW),)
        ),
    )
    service = ActiveIncidentsService(
        ProviderRegistry(
            (
                _registration("Failed floods", failed, Disaster.FLOOD),
                _registration("Earthquakes", earthquake, Disaster.EARTHQUAKE),
            )
        ),
        clock=lambda: NOW,
    )

    snapshot = await service.execute()

    assert [item.event_id for item in snapshot.incidents] == ["quake"]
    assert _coverage(snapshot)[Disaster.FLOOD].state is IncidentCoverageState.DEGRADED
    assert _coverage(snapshot)[Disaster.EARTHQUAKE].state is (
        IncidentCoverageState.EVENTS_FOUND
    )
    assert snapshot.warnings == (
        "Worldwide provider Failed floods could not be reached or returned "
        "invalid data.",
    )
    assert "secret failure" not in snapshot.warnings[0]


@pytest.mark.asyncio
async def test_source_policy_invalid_records_are_excluded() -> None:
    invalid = FakeWorldwideProvider(
        "approved-source",
        ProviderBatch((_event("spoofed-source", Disaster.WILDFIRE, "bad", NOW),)),
    )
    service = ActiveIncidentsService(
        ProviderRegistry((_registration("Wildfires", invalid, Disaster.WILDFIRE),)),
        clock=lambda: NOW,
    )

    snapshot = await service.execute()

    assert snapshot.incidents == ()
    assert _coverage(snapshot)[Disaster.WILDFIRE].state is (
        IncidentCoverageState.DEGRADED
    )
    assert snapshot.warnings == (
        "A worldwide disaster record violated source policy and was excluded.",
    )


@pytest.mark.asyncio
async def test_successful_empty_result_differs_from_provider_failure() -> None:
    empty = FakeWorldwideProvider("empty-earthquakes", ProviderBatch())
    failed = FakeWorldwideProvider("failed-floods", RuntimeError("offline"))
    service = ActiveIncidentsService(
        ProviderRegistry(
            (
                _registration("Empty earthquakes", empty, Disaster.EARTHQUAKE),
                _registration("Failed floods", failed, Disaster.FLOOD),
            )
        ),
        clock=lambda: NOW,
    )

    snapshot = await service.execute()

    assert _coverage(snapshot)[Disaster.EARTHQUAKE].state is (
        IncidentCoverageState.NO_MATCHING_RECORDS
    )
    assert _coverage(snapshot)[Disaster.FLOOD].state is IncidentCoverageState.DEGRADED


@pytest.mark.asyncio
async def test_unconfigured_worldwide_coverage_is_unavailable() -> None:
    provider = FakeWorldwideProvider("wildfires", ProviderBatch())
    service = ActiveIncidentsService(
        ProviderRegistry(
            (
                _registration(
                    "Unconfigured wildfires",
                    provider,
                    Disaster.WILDFIRE,
                    configured=False,
                ),
            )
        ),
        clock=lambda: NOW,
    )

    snapshot = await service.execute()

    assert _coverage(snapshot)[Disaster.WILDFIRE].state is (
        IncidentCoverageState.UNAVAILABLE
    )
    assert provider.queries == []


@pytest.mark.asyncio
async def test_query_bounds_are_enforced_and_results_are_bounded() -> None:
    with pytest.raises(ValueError, match="time_window_days"):
        ActiveIncidentsQuery(time_window_days=0)
    with pytest.raises(ValueError, match="time_window_days"):
        ActiveIncidentsQuery(time_window_days=31)
    with pytest.raises(ValueError, match="limit_per_disaster"):
        ActiveIncidentsQuery(limit_per_disaster=0)
    with pytest.raises(ValueError, match="limit_per_disaster"):
        ActiveIncidentsQuery(limit_per_disaster=21)

    events = tuple(
        _event(
            "earthquakes",
            Disaster.EARTHQUAKE,
            f"quake-{index}",
            NOW - timedelta(minutes=index),
        )
        for index in range(5)
    )
    provider = FakeWorldwideProvider("earthquakes", ProviderBatch(events))
    service = ActiveIncidentsService(
        ProviderRegistry(
            (_registration("Earthquakes", provider, Disaster.EARTHQUAKE),)
        ),
        clock=lambda: NOW,
    )

    snapshot = await service.execute(
        ActiveIncidentsQuery(time_window_days=3, limit_per_disaster=2)
    )

    assert [item.event_id for item in snapshot.incidents] == ["quake-0", "quake-1"]
    provider_query, provider_now = provider.queries[0]
    assert provider_query.time_window_days == 3
    assert provider_query.limit == 2
    assert provider_now == NOW


@pytest.mark.asyncio
async def test_descriptive_geometry_remains_without_coordinates() -> None:
    provider = FakeWorldwideProvider(
        "cyclones",
        ProviderBatch(
            (
                _event(
                    "cyclones",
                    Disaster.TROPICAL_CYCLONE,
                    "storm",
                    NOW,
                    descriptive=True,
                ),
            )
        ),
    )
    service = ActiveIncidentsService(
        ProviderRegistry(
            (_registration("Cyclones", provider, Disaster.TROPICAL_CYCLONE),)
        ),
        clock=lambda: NOW,
    )

    snapshot = await service.execute()

    geometry = snapshot.incidents[0].geometry
    assert geometry is not None
    assert geometry.kind.value == "descriptive"
    assert geometry.coordinates == ()
    assert snapshot.incidents[0].source_authority is (
        SourceAuthority.SCIENTIFIC_AUTHORITY
    )
