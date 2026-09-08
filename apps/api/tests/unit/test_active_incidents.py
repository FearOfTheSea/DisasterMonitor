from datetime import timedelta

import pytest

from disaster_monitor.application.disaster import (
    ObservationKind,
    ProviderBatch,
    ProviderIssue,
    WorldwideDisasterEvent,
)
from disaster_monitor.application.incidents.active_incidents import (
    ActiveIncidentsQuery,
    IncidentCoverageState,
)
from disaster_monitor.application.sources.provider_registry import ProviderRegistry
from disaster_monitor.domain.disaster import (
    Disaster,
    ProviderTier,
    SourceAuthority,
    WatchCoverageState,
    point_event_geometry,
)

from .active_incidents_support import (
    NOW,
    FakeWorldwideProvider,
    _active_incidents_service,
    _coverage,
    _event,
    _registration,
    _source,
    _watch,
)


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
    service = _active_incidents_service(
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
async def test_labels_on_land_coordinates_for_each_disaster() -> None:
    providers = tuple(
        _registration(
            f"{disaster.value}-source",
            FakeWorldwideProvider(
                f"{disaster.value}-source",
                ProviderBatch(
                    (
                        _event(
                            f"{disaster.value}-source",
                            disaster,
                            f"{disaster.value}-event",
                            NOW,
                            latitude=32.5,
                            longitude=133.5,
                        ),
                    )
                ),
            ),
            disaster,
        )
        for disaster in Disaster
    )
    service = _active_incidents_service(
        ProviderRegistry(providers),
        clock=lambda: NOW,
    )

    snapshot = await service.execute()

    assert len(snapshot.incidents) == len(Disaster)
    assert {item.country.country_name for item in snapshot.incidents} == {"Japan"}
    assert {item.location for item in snapshot.incidents} == {
        f"{disaster.value} location" for disaster in Disaster
    }


@pytest.mark.asyncio
async def test_retains_record_when_country_cannot_be_resolved() -> None:
    provider = FakeWorldwideProvider(
        "offshore-floods",
        ProviderBatch(
            (
                _event(
                    "offshore-floods",
                    Disaster.FLOOD,
                    "offshore-flood",
                    NOW,
                    latitude=0.0,
                    longitude=0.0,
                ),
            )
        ),
    )
    service = _active_incidents_service(
        ProviderRegistry((_registration("Offshore floods", provider, Disaster.FLOOD),)),
        clock=lambda: NOW,
    )

    snapshot = await service.execute()

    assert [item.event_id for item in snapshot.incidents] == ["offshore-flood"]
    assert snapshot.incidents[0].country is None
    assert _coverage(snapshot)[Disaster.FLOOD].state is (
        IncidentCoverageState.EVENTS_FOUND
    )
    assert snapshot.warnings == (
        "A worldwide event has no trusted country association and is retained as a "
        "countryless incident.",
    )


@pytest.mark.asyncio
async def test_uses_source_country_when_coordinate_is_offshore() -> None:
    provider = FakeWorldwideProvider(
        "offshore-earthquakes",
        ProviderBatch(
            (
                _event(
                    "offshore-earthquakes",
                    Disaster.EARTHQUAKE,
                    "offshore-earthquake",
                    NOW,
                    latitude=0.0,
                    longitude=0.0,
                    location="OFFSHORE REGION, VIETNAM",
                ),
            )
        ),
    )
    service = _active_incidents_service(
        ProviderRegistry(
            (_registration("Offshore earthquakes", provider, Disaster.EARTHQUAKE),)
        ),
        clock=lambda: NOW,
    )

    snapshot = await service.execute()

    assert snapshot.incidents[0].country.country_name == "Vietnam"
    assert snapshot.incidents[0].location == "OFFSHORE REGION, VIETNAM"


@pytest.mark.asyncio
async def test_union_of_provider_tiers_preserves_distinct_records() -> None:
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
                    NOW - timedelta(hours=1),
                ),
            )
        ),
    )
    service = _active_incidents_service(
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

    assert [item.event_id for item in snapshot.incidents] == ["primary", "secondary"]
    assert {item.provider_tier for item in snapshot.incidents} == {
        ProviderTier.PRIMARY,
        ProviderTier.SECONDARY,
    }


@pytest.mark.asyncio
async def test_worldwide_earthquake_identity_merges_cross_source_events() -> None:
    emsc = FakeWorldwideProvider(
        "emsc-earthquakes",
        ProviderBatch(
            (
                _event(
                    "emsc-earthquakes",
                    Disaster.EARTHQUAKE,
                    "emsc-1",
                    NOW,
                    latitude=35.0,
                    longitude=139.0,
                ),
                _event(
                    "emsc-earthquakes",
                    Disaster.EARTHQUAKE,
                    "emsc-unrelated",
                    NOW,
                    latitude=36.5,
                    longitude=140.5,
                ),
            )
        ),
    )
    usgs = FakeWorldwideProvider(
        "usgs-earthquakes",
        ProviderBatch(
            (
                _event(
                    "usgs-earthquakes",
                    Disaster.EARTHQUAKE,
                    "usgs-1",
                    NOW - timedelta(seconds=30),
                    latitude=35.01,
                    longitude=139.01,
                ),
            )
        ),
    )
    service = _active_incidents_service(
        ProviderRegistry(
            (
                _registration("EMSC", emsc, Disaster.EARTHQUAKE),
                _registration("USGS", usgs, Disaster.EARTHQUAKE),
            )
        ),
        clock=lambda: NOW,
    )

    snapshot = await service.execute()

    assert len(snapshot.incidents) == 2
    matched = next(item for item in snapshot.incidents if item.event_id == "emsc-1")
    assert matched.physical_event_id is not None
    assert {item.source_id for item in matched.evidence_sources} == {
        "emsc-earthquakes",
        "usgs-earthquakes",
    }
    assert {item.event_id for item in snapshot.incidents} == {
        "emsc-1",
        "emsc-unrelated",
    }


@pytest.mark.asyncio
async def test_acquisition_observations_are_separate_from_incident_counts() -> None:
    provider = FakeWorldwideProvider(
        "gfm-observations",
        ProviderBatch(
            (
                WorldwideDisasterEvent(
                    event_id="acquisition-1",
                    disaster=Disaster.FLOOD,
                    location="Sentinel acquisition",
                    event_time=NOW,
                    source=_source("gfm-observations", NOW),
                    geometry=point_event_geometry(
                        32.5,
                        133.5,
                        _source("gfm-observations", NOW),
                        estimated=True,
                    ),
                    observation_kind=ObservationKind.ACQUISITION,
                ),
            )
        ),
    )
    service = _active_incidents_service(
        ProviderRegistry((_registration("GFM", provider, Disaster.FLOOD),)),
        clock=lambda: NOW,
    )

    snapshot = await service.execute()

    assert snapshot.incidents == ()
    assert len(snapshot.observations) == 1
    assert snapshot.observations[0].observation_kind is ObservationKind.ACQUISITION
    assert _coverage(snapshot)[Disaster.FLOOD].incident_count == 0


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
    service = _active_incidents_service(
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
    service = _active_incidents_service(
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
    service = _active_incidents_service(
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
    service = _active_incidents_service(
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
    service = _active_incidents_service(
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
async def test_watch_observation_preserves_empty_failure_stale_and_unavailable() -> (
    None
):
    empty = FakeWorldwideProvider("empty-earthquakes", ProviderBatch())
    failed = FakeWorldwideProvider("failed-floods", RuntimeError("offline"))
    stale = FakeWorldwideProvider(
        "stale-wildfires",
        ProviderBatch(
            (
                _event(
                    "stale-wildfires",
                    Disaster.WILDFIRE,
                    "old-fire",
                    NOW - timedelta(days=2),
                ),
            )
        ),
    )
    service = _active_incidents_service(
        ProviderRegistry(
            (
                _registration("Empty earthquakes", empty, Disaster.EARTHQUAKE),
                _registration("Failed floods", failed, Disaster.FLOOD),
                _registration("Stale wildfires", stale, Disaster.WILDFIRE),
            )
        ),
        clock=lambda: NOW,
    )

    no_match = await service.observe_watch(_watch(Disaster.EARTHQUAKE))
    degraded = await service.observe_watch(_watch(Disaster.FLOOD))
    stale_result = await service.observe_watch(_watch(Disaster.WILDFIRE))
    unavailable = await service.observe_watch(_watch(Disaster.LANDSLIDE))

    assert no_match.coverage_state is WatchCoverageState.NO_MATCHING_RECORDS
    assert no_match.successful is True
    assert degraded.coverage_state is WatchCoverageState.DEGRADED
    assert degraded.successful is False and degraded.retryable is True
    assert degraded.provider_source_ids == ("failed-floods",)
    assert stale_result.coverage_state is WatchCoverageState.STALE
    assert stale_result.successful is False
    assert unavailable.coverage_state is WatchCoverageState.UNAVAILABLE
    assert unavailable.successful is False


@pytest.mark.asyncio
async def test_query_bounds_separate_acquisition_from_result_paging() -> None:
    with pytest.raises(ValueError, match="time_window_days"):
        ActiveIncidentsQuery(time_window_days=0)
    with pytest.raises(ValueError, match="time_window_days"):
        ActiveIncidentsQuery(time_window_days=31)
    with pytest.raises(ValueError, match="limit_per_disaster"):
        ActiveIncidentsQuery(limit_per_disaster=0)
    with pytest.raises(ValueError, match="limit_per_disaster"):
        ActiveIncidentsQuery(limit_per_disaster=21)
    with pytest.raises(ValueError, match="acquisition_limit_per_disaster"):
        ActiveIncidentsQuery(acquisition_limit_per_disaster=0)
    with pytest.raises(ValueError, match="acquisition_limit_per_disaster"):
        ActiveIncidentsQuery(acquisition_limit_per_disaster=501)

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
    service = _active_incidents_service(
        ProviderRegistry(
            (_registration("Earthquakes", provider, Disaster.EARTHQUAKE),)
        ),
        clock=lambda: NOW,
    )

    snapshot = await service.execute(
        ActiveIncidentsQuery(
            time_window_days=3,
            limit_per_disaster=2,
            acquisition_limit_per_disaster=4,
        )
    )

    assert [item.event_id for item in snapshot.incidents] == [
        "quake-0",
        "quake-1",
        "quake-2",
        "quake-3",
        "quake-4",
    ]
    provider_query, provider_now = provider.queries[0]
    assert provider_query.time_window_days == 3
    assert provider_query.limit == 4
    assert provider_now == NOW


@pytest.mark.asyncio
async def test_incomplete_provider_scan_is_distinct_from_page_continuation() -> None:
    provider = FakeWorldwideProvider(
        "earthquakes",
        ProviderBatch(
            (
                _event(
                    "earthquakes",
                    Disaster.EARTHQUAKE,
                    "quake-1",
                    NOW,
                ),
            ),
            scan_complete=False,
            records_seen=50,
        ),
    )
    service = _active_incidents_service(
        ProviderRegistry(
            (_registration("Earthquakes", provider, Disaster.EARTHQUAKE),)
        ),
        clock=lambda: NOW,
    )

    snapshot = await service.execute(ActiveIncidentsQuery(page_size=3))

    coverage = _coverage(snapshot)[Disaster.EARTHQUAKE]
    assert snapshot.has_more is False
    assert coverage.scan_complete is False
    assert coverage.records_seen == 50
    assert coverage.truncated is True


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
                    location="Japan",
                ),
            )
        ),
    )
    service = _active_incidents_service(
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
