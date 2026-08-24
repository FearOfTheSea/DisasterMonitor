from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from disaster_monitor.application.disaster import DisasterQuery
from disaster_monitor.application.services.event_resolution import (
    DefaultEventPolicy,
    EarthquakeEventPolicy,
    default_event_policy_registry,
)
from disaster_monitor.domain.disaster import (
    Disaster,
    DisasterEvent,
    EarthquakeEvent,
    EventMeasurement,
    MeasurementKind,
    SourceReference,
    point_event_geometry,
)
from disaster_monitor.infrastructure.geography.static_country_catalog import (
    StaticCountryCatalog,
)

NOW = datetime(2026, 8, 6, 3, 0, tzinfo=UTC)
CATALOG = StaticCountryCatalog()
JAPAN = CATALOG.get_by_alpha3("JPN")
VENEZUELA = CATALOG.get_by_alpha3("VEN")
assert JAPAN is not None and VENEZUELA is not None
SOURCE = SourceReference(
    "usgs-earthquakes",
    "USGS",
    "Fixture",
    "https://example.test/event",
    NOW,
    NOW,
    NOW,
)


def _event(event_id: str, **changes: object) -> EarthquakeEvent:
    latitude = float(changes.pop("latitude", 37.0))
    longitude = float(changes.pop("longitude", 137.0))
    magnitude = float(changes.pop("magnitude", 6.1))
    event = EarthquakeEvent(
        event_id,
        Disaster.EARTHQUAKE,
        "Ishikawa, Japan",
        JAPAN,
        NOW - timedelta(hours=2),
        SOURCE,
        geometry=point_event_geometry(latitude, longitude, SOURCE),
        measurements=(
            EventMeasurement(MeasurementKind.MAGNITUDE, magnitude, source=SOURCE),
        ),
        provider_ids=(event_id,),
    )
    return replace(event, **changes)


def _generic_event(event_id: str, **changes: object) -> DisasterEvent:
    disaster = changes.pop("disaster", Disaster.FLOOD)
    country = changes.pop("country", JAPAN)
    event_time = changes.pop("event_time", NOW - timedelta(hours=2))
    return DisasterEvent(
        event_id=event_id,
        disaster=disaster,
        location="Ishikawa, Japan",
        country=country,
        event_time=event_time,
        source=SOURCE,
        geometry=point_event_geometry(37.0, 137.0, SOURCE),
        measurements=(EventMeasurement(MeasurementKind.MAGNITUDE, 6.1, source=SOURCE),),
        provider_ids=(event_id,),
    )


def _provider_event(
    disaster: Disaster,
    source_id: str,
    event_id: str,
    *,
    event_time: datetime,
    latitude: float,
    longitude: float,
) -> DisasterEvent:
    source = SourceReference(
        source_id,
        source_id,
        "Source-backed event observation",
        f"https://{source_id}.example/{event_id}",
        event_time,
        event_time,
        NOW,
    )
    return DisasterEvent(
        event_id=event_id,
        disaster=disaster,
        location="Japan",
        country=JAPAN,
        event_time=event_time,
        source=source,
        geometry=point_event_geometry(latitude, longitude, source),
        provider_ids=(event_id,),
    )


def test_earthquake_policy_clusters_cross_provider_observations() -> None:
    policy = EarthquakeEventPolicy()
    observations = (
        _event("global-catalog:target"),
        _event(
            "usgs:target",
            event_time=NOW - timedelta(hours=2, seconds=-20),
            latitude=37.02,
            longitude=137.01,
        ),
    )
    identity = policy.identify(observations)
    clustered = policy.cluster(observations)

    assert len(clustered) == 1
    assert set(clustered[0].provider_ids) == {"global-catalog:target", "usgs:target"}
    assert {
        observation.event_id for observation in identity.physical_events[0].observations
    } == {observation.event_id for observation in observations}
    assert all(
        assignment.rationale for assignment in identity.physical_events[0].assignments
    )


def test_earthquake_policy_never_clusters_across_country_or_disaster() -> None:
    policy = EarthquakeEventPolicy()
    clustered = policy.cluster(
        (
            _event("japan"),
            _event("foreign", country=VENEZUELA),
            _generic_event("flood"),
        )
    )

    assert len(clustered) == 3


def test_nearby_independent_earthquakes_are_not_merged() -> None:
    policy = EarthquakeEventPolicy()
    clustered = policy.cluster(
        (_event("first", magnitude=5.0), _event("second", magnitude=6.0))
    )

    assert len(clustered) == 2


def test_default_policy_marks_similarly_recent_independent_events_ambiguous() -> None:
    policy = DefaultEventPolicy()
    query = DisasterQuery(Disaster.FLOOD, JAPAN, "recent", ("latest",))
    first = _generic_event("first")
    second = _generic_event(
        "second",
        disaster=Disaster.FLOOD,
        event_time=first.event_time - timedelta(hours=1),
    )

    resolution = policy.resolve((first, second), query, now=NOW)

    assert resolution.selected == first
    assert resolution.ambiguous is True


def test_default_policy_never_merges_shared_ids_across_scope() -> None:
    policy = DefaultEventPolicy()
    flood = _generic_event("shared:event")
    foreign = _generic_event("shared:event", disaster=Disaster.FLOOD, country=VENEZUELA)
    earthquake = _event("shared:event")

    identity = policy.identify((flood, foreign, earthquake))

    assert len(identity.physical_events) == 3


def test_generic_policy_ignores_earthquake_measurements_when_ranking_floods() -> None:
    policy = DefaultEventPolicy()
    older = replace(
        _generic_event("older"),
        event_time=NOW - timedelta(hours=2),
    )
    newer = replace(
        _generic_event("newer", event_time=NOW - timedelta(hours=1)),
    )

    resolution = policy.resolve(
        (older, newer),
        DisasterQuery(Disaster.FLOOD, JAPAN, "recent", ("latest",)),
        now=NOW,
    )

    assert resolution.selected == newer


def test_volcanic_policy_accepts_current_wvar_observation_of_ongoing_eruption() -> None:
    source = replace(
        SOURCE,
        source_id="smithsonian-usgs-volcanic-activity",
        published_at=NOW - timedelta(hours=1),
    )
    event = _generic_event(
        "gvp-eruption:22203",
        disaster=Disaster.VOLCANIC_ERUPTION,
        event_time=datetime(2017, 3, 25, tzinfo=UTC),
    )
    event = replace(event, source=source)
    query = DisasterQuery(Disaster.VOLCANIC_ERUPTION, JAPAN, "current", ("latest",))

    resolution = (
        default_event_policy_registry()
        .for_disaster(Disaster.VOLCANIC_ERUPTION)
        .resolve((event,), query, now=NOW)
    )

    assert resolution.selected == event


def test_volcanic_policy_does_not_refresh_old_events_from_unrelated_sources() -> None:
    event = _generic_event(
        "old-volcano",
        disaster=Disaster.VOLCANIC_ERUPTION,
        event_time=datetime(2017, 3, 25, tzinfo=UTC),
    )
    query = DisasterQuery(Disaster.VOLCANIC_ERUPTION, JAPAN, "current", ("latest",))

    resolution = (
        default_event_policy_registry()
        .for_disaster(Disaster.VOLCANIC_ERUPTION)
        .resolve((event,), query, now=NOW)
    )

    assert resolution.selected is None


@pytest.mark.parametrize(
    ("disaster", "primary_source", "gdacs_source", "time_delta", "point_delta"),
    (
        (
            Disaster.FLOOD,
            "cems-gfm-floods",
            "gdacs-floods",
            timedelta(hours=24),
            0.1,
        ),
        (
            Disaster.WILDFIRE,
            "nasa-eonet-wildfires",
            "gdacs-wildfires",
            timedelta(hours=24),
            0.1,
        ),
        (
            Disaster.VOLCANIC_ERUPTION,
            "smithsonian-usgs-volcanic-activity",
            "gdacs-volcanic-eruptions",
            timedelta(days=3),
            0.03,
        ),
    ),
)
def test_secondary_gdacs_observation_of_same_real_event_is_reconciled(
    disaster: Disaster,
    primary_source: str,
    gdacs_source: str,
    time_delta: timedelta,
    point_delta: float,
) -> None:
    observations = (
        _provider_event(
            disaster,
            primary_source,
            f"{primary_source}:event-a",
            event_time=NOW - timedelta(days=4),
            latitude=35.0,
            longitude=139.0,
        ),
        _provider_event(
            disaster,
            gdacs_source,
            f"{gdacs_source}:unrelated-id",
            event_time=NOW - timedelta(days=4) + time_delta,
            latitude=35.0 + point_delta,
            longitude=139.0,
        ),
    )

    identity = (
        default_event_policy_registry().for_disaster(disaster).identify(observations)
    )

    assert len(identity.physical_events) == 1
    assert {item.event_id for item in identity.physical_events[0].observations} == {
        item.event_id for item in observations
    }


@pytest.mark.parametrize(
    ("disaster", "primary_source", "gdacs_source", "point_delta"),
    (
        (
            Disaster.FLOOD,
            "cems-gfm-floods",
            "gdacs-floods",
            0.4,
        ),
        (
            Disaster.WILDFIRE,
            "nasa-eonet-wildfires",
            "gdacs-wildfires",
            0.3,
        ),
        (
            Disaster.VOLCANIC_ERUPTION,
            "smithsonian-usgs-volcanic-activity",
            "gdacs-volcanic-eruptions",
            0.1,
        ),
    ),
)
def test_nearby_distinct_primary_and_gdacs_events_are_not_merged(
    disaster: Disaster,
    primary_source: str,
    gdacs_source: str,
    point_delta: float,
) -> None:
    observations = (
        _provider_event(
            disaster,
            primary_source,
            f"{primary_source}:event-a",
            event_time=NOW - timedelta(days=1),
            latitude=35.0,
            longitude=139.0,
        ),
        _provider_event(
            disaster,
            gdacs_source,
            f"{gdacs_source}:event-b",
            event_time=NOW - timedelta(days=1),
            latitude=35.0 + point_delta,
            longitude=139.0,
        ),
    )

    identity = (
        default_event_policy_registry().for_disaster(disaster).identify(observations)
    )

    assert len(identity.physical_events) == 2


def test_earthquake_sequence_and_aftershock_policy_remains_disaster_specific() -> None:
    policy = EarthquakeEventPolicy()
    mainshock = _event("mainshock")
    aftershock = _event(
        "aftershock",
        event_time=mainshock.event_time + timedelta(hours=2),
        latitude=37.2,
        is_aftershock=True,
        parent_event_id="mainshock",
    )

    assert policy.same_sequence(mainshock, aftershock)
    assert policy.same_physical_event(mainshock, aftershock) is False


def test_earthquake_subtype_rejects_non_earthquake_disaster() -> None:
    with pytest.raises(ValueError, match="requires the earthquake disaster"):
        replace(_event("earthquake"), disaster=Disaster.FLOOD)
