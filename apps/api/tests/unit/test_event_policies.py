from dataclasses import replace
from datetime import UTC, datetime, timedelta

from disaster_monitor.application.disaster import DisasterQuery
from disaster_monitor.application.services.event_resolution import (
    DefaultEventPolicy,
    EarthquakeEventPolicy,
)
from disaster_monitor.domain.disaster import (
    EarthquakeEvent,
    EventMeasurement,
    Hazard,
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
        Hazard.EARTHQUAKE,
        "Ishikawa, Japan",
        JAPAN,
        NOW - timedelta(hours=2),
        SOURCE,
        geometry=point_event_geometry(latitude, longitude, SOURCE),
        measurements=(EventMeasurement("magnitude", magnitude),),
        provider_ids=(event_id,),
    )
    return replace(event, **changes)


def test_earthquake_policy_clusters_cross_provider_observations() -> None:
    policy = EarthquakeEventPolicy()
    observations = (
        _event("jma:target"),
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
    assert set(clustered[0].provider_ids) == {"jma:target", "usgs:target"}
    assert identity.physical_events[0].observations == observations
    assert all(
        assignment.rationale for assignment in identity.physical_events[0].assignments
    )


def test_earthquake_policy_never_clusters_across_country_or_hazard() -> None:
    policy = EarthquakeEventPolicy()
    clustered = policy.cluster(
        (
            _event("japan"),
            _event("foreign", country=VENEZUELA),
            _event("flood", hazard=Hazard.FLOOD),
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
    query = DisasterQuery(Hazard.FLOOD, JAPAN, "recent", ("latest",))
    first = _event("first", hazard=Hazard.FLOOD)
    second = _event(
        "second", hazard=Hazard.FLOOD, event_time=first.event_time - timedelta(hours=1)
    )

    resolution = policy.resolve((first, second), query, now=NOW)

    assert resolution.selected == first
    assert resolution.ambiguous is True


def test_default_policy_never_merges_shared_ids_across_scope() -> None:
    policy = DefaultEventPolicy()
    flood = _event("shared:event", hazard=Hazard.FLOOD)
    foreign = _event("shared:event", hazard=Hazard.FLOOD, country=VENEZUELA)
    earthquake = _event("shared:event", hazard=Hazard.EARTHQUAKE)

    identity = policy.identify((flood, foreign, earthquake))

    assert len(identity.physical_events) == 3


def test_generic_policy_ignores_earthquake_measurements_when_ranking_floods() -> None:
    policy = DefaultEventPolicy()
    older = replace(
        _event("older", magnitude=9.0),
        hazard=Hazard.FLOOD,
        event_time=NOW - timedelta(hours=2),
    )
    newer = replace(
        _event("newer", magnitude=1.0),
        hazard=Hazard.FLOOD,
        event_time=NOW - timedelta(hours=1),
    )

    resolution = policy.resolve(
        (older, newer),
        DisasterQuery(Hazard.FLOOD, JAPAN, "recent", ("latest",)),
        now=NOW,
    )

    assert resolution.selected == newer
