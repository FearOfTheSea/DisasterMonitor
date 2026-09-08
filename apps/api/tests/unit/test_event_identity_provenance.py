from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from disaster_monitor.application.disaster import DisasterQuery
from disaster_monitor.application.evidence.event_identity import (
    event_observation_key,
    provider_identifiers,
)
from disaster_monitor.application.evidence.event_resolution import (
    DefaultEventPolicy,
    WildfireEventPolicy,
)
from disaster_monitor.application.evidence.source_evidence_policy import (
    validate_physical_event_evidence,
)
from disaster_monitor.application.ports.source_evidence import (
    SourceEvidencePolicyError,
)
from disaster_monitor.domain.disaster import (
    Disaster,
    DisasterEvent,
    EventMeasurement,
    MeasurementKind,
    SourceReference,
    point_event_geometry,
)
from disaster_monitor.infrastructure.geography.static_country_catalog import (
    StaticCountryCatalog,
)

NOW = datetime(2026, 8, 18, 12, tzinfo=UTC)
JAPAN = StaticCountryCatalog().get_by_alpha3("JPN")
assert JAPAN is not None


def _source(source_id: str, *, age: timedelta = timedelta()) -> SourceReference:
    timestamp = NOW - age
    return SourceReference(
        source_id=source_id,
        publisher=source_id,
        title="Fixture observation",
        canonical_url=f"https://{source_id}.example/events",
        published_at=timestamp,
        updated_at=timestamp,
        retrieved_at=timestamp,
    )


def _event(
    source: SourceReference,
    *,
    event_id: str = "flood:shared",
    geometry=None,
    measurements: tuple[EventMeasurement, ...] = (),
    provider_ids: tuple[str, ...] | None = None,
    lineage_ids: tuple[str, ...] = (),
    event_time: datetime = NOW,
) -> DisasterEvent:
    return DisasterEvent(
        event_id=event_id,
        disaster=Disaster.FLOOD,
        location="Japan",
        country=JAPAN,
        event_time=event_time,
        source=source,
        geometry=geometry,
        measurements=measurements,
        provider_ids=provider_ids if provider_ids is not None else (event_id,),
        lineage_ids=lineage_ids,
    )


def _query() -> DisasterQuery:
    return DisasterQuery(Disaster.FLOOD, JAPAN, "recent", ("latest",))


def test_generic_policy_merges_shared_provider_identity_within_safe_timing() -> None:
    source_a = _source("flood-a")
    source_b = _source("flood-b", age=timedelta(hours=1))
    identity = DefaultEventPolicy().identify(
        (
            _event(source_a),
            _event(source_b, event_time=NOW - timedelta(minutes=10)),
        )
    )

    assert len(identity.physical_events) == 1
    assert set(identity.physical_events[0].event.provider_ids) == {"flood:shared"}


def test_generic_policy_keeps_events_separate_without_identity_evidence() -> None:
    source_a = _source("flood-a")
    source_b = _source("flood-b")
    first = _event(source_a, event_id="flood:first")
    second = _event(
        source_b,
        event_id="flood:second",
        event_time=NOW - timedelta(minutes=1),
    )

    identity = DefaultEventPolicy().identify((first, second))

    assert len(identity.physical_events) == 2


def test_generic_provider_labels_do_not_create_cross_event_identity() -> None:
    first = _event(
        _source("nasa-eonet-wildfires"),
        event_id="eonet:EONET_24104",
        provider_ids=("GDACS",),
    )
    second = _event(
        _source("nasa-eonet-wildfires"),
        event_id="eonet:EONET_24106",
        provider_ids=("GDACS",),
    )

    assert provider_identifiers(first) == {"eonet:eonet_24104"}
    assert provider_identifiers(second) == {"eonet:eonet_24106"}
    assert len(DefaultEventPolicy().identify((first, second)).physical_events) == 2


def test_three_australian_eonet_observations_with_bare_gdacs_label_stay_separate() -> (
    None
):
    source = _source("nasa-eonet-wildfires")
    fixtures = (
        ("EONET_24104", -17.209298692387, 126.08467536061),
        ("EONET_24106", -18.176931416409, 137.9597861365),
        ("EONET_24107", -19.663703232326, 145.62701520916),
    )
    events = tuple(
        replace(
            _event(
                source,
                event_id=f"eonet:{event_id}",
                provider_ids=("GDACS",),
                event_time=NOW - timedelta(days=index),
                geometry=point_event_geometry(latitude, longitude, source),
            ),
            disaster=Disaster.WILDFIRE,
            location="Australia",
        )
        for index, (event_id, latitude, longitude) in enumerate(fixtures)
    )

    identity = WildfireEventPolicy().identify(events).physical_events

    assert len(identity) == 3
    assert {event.event.event_id for event in identity} == {
        "eonet:EONET_24104",
        "eonet:EONET_24106",
        "eonet:EONET_24107",
    }


def test_validated_upstream_lineage_reconciles_and_keeps_provenance() -> None:
    eonet_source = _source("nasa-eonet-wildfires")
    gdacs_source = _source("gdacs-wildfires", age=timedelta(minutes=10))
    eonet = _event(
        eonet_source,
        event_id="eonet:EONET_24104",
        provider_ids=("eonet:EONET_24104",),
        lineage_ids=("gdacs:wf:1031816",),
    )
    gdacs = _event(
        gdacs_source,
        event_id="gdacs:wf:1031816",
        provider_ids=("gdacs:wf:1031816",),
        event_time=NOW - timedelta(minutes=5),
    )

    identity = DefaultEventPolicy().identify((eonet, gdacs)).physical_events

    assert len(identity) == 1
    assert identity[0].event.lineage_ids == ("gdacs:wf:1031816",)
    assert {item.source.source_id for item in identity[0].observations} == {
        "nasa-eonet-wildfires",
        "gdacs-wildfires",
    }


def test_merge_keeps_measurement_provenance_and_deduplicates_exact_observations() -> (
    None
):
    source_a = _source("flood-a")
    source_b = _source("flood-b", age=timedelta(hours=1))
    measurement_a = EventMeasurement(MeasurementKind.CONFIDENCE, 0.8, source=source_a)
    measurement_b = EventMeasurement(MeasurementKind.CONFIDENCE, 0.8, source=source_b)
    identity = (
        DefaultEventPolicy()
        .identify(
            (
                _event(source_a, measurements=(measurement_a,)),
                _event(source_b, measurements=(measurement_b,)),
            )
        )
        .physical_events[0]
    )

    assert set(identity.event.measurements) == {measurement_a, measurement_b}
    assert {item.source.source_id for item in identity.event.measurements} == {
        "flood-a",
        "flood-b",
    }


def test_preferred_geometry_retains_its_own_provenance() -> None:
    source_a = _source("flood-a")
    source_b = _source("flood-b", age=timedelta(hours=1))
    geometry_a = point_event_geometry(35.0, 139.0, source_a)
    geometry_b = point_event_geometry(36.0, 140.0, source_b)
    identity = (
        DefaultEventPolicy()
        .identify(
            (
                _event(source_a, geometry=geometry_a),
                _event(source_b, geometry=geometry_b),
            )
        )
        .physical_events[0]
    )

    assert identity.event.source is source_a
    assert identity.event.geometry is geometry_a
    assert {item.geometry.source.source_id for item in identity.observations} == {
        "flood-a",
        "flood-b",
    }
    validate_physical_event_evidence(identity.event, identity, _query())


def test_geometry_from_non_preferred_observation_remains_independently_attributed() -> (
    None
):
    source_a = _source("flood-a")
    source_b = _source("flood-b", age=timedelta(hours=1))
    geometry_b = point_event_geometry(36.0, 140.0, source_b)
    identity = (
        DefaultEventPolicy()
        .identify(
            (
                _event(source_a),
                _event(source_b, geometry=geometry_b),
            )
        )
        .physical_events[0]
    )

    assert identity.event.source is source_a
    assert identity.event.geometry is geometry_b
    assert identity.event.geometry.source is source_b
    validate_physical_event_evidence(identity.event, identity, _query())


def test_conflicting_source_geometries_are_retained_as_observations() -> None:
    source_a = _source("flood-a")
    source_b = _source("flood-b", age=timedelta(hours=1))
    geometry_a = point_event_geometry(35.0, 139.0, source_a)
    geometry_b = point_event_geometry(36.0, 140.0, source_b)
    identity = (
        DefaultEventPolicy()
        .identify(
            (
                _event(source_a, geometry=geometry_a),
                _event(source_b, geometry=geometry_b),
            )
        )
        .physical_events[0]
    )

    assert identity.event.geometry is geometry_a
    assert geometry_b in tuple(
        item.geometry for item in identity.observations if item.geometry is not None
    )


def test_unobserved_geometry_provenance_is_rejected_fail_closed() -> None:
    source_a = _source("flood-a")
    source_b = _source("flood-b", age=timedelta(hours=1))
    identity = (
        DefaultEventPolicy()
        .identify((_event(source_a), _event(source_b)))
        .physical_events[0]
    )
    unapproved = point_event_geometry(1.0, 2.0, _source("unapproved"))

    with pytest.raises(SourceEvidencePolicyError, match="geometry provenance"):
        validate_physical_event_evidence(
            replace(identity.event, geometry=unapproved), identity, _query()
        )


def test_physical_event_id_survives_later_corroboration() -> None:
    first = _event(_source("emsc-earthquakes"), event_id="quake:shared")
    second = _event(
        _source("usgs-earthquakes", age=timedelta(minutes=1)),
        event_id="quake:shared",
        event_time=NOW - timedelta(seconds=20),
    )
    third = _event(
        _source("secondary-earthquakes", age=timedelta(minutes=2)),
        event_id="quake:shared",
        event_time=NOW - timedelta(seconds=10),
    )
    policy = DefaultEventPolicy()

    established = policy.identify((first, second)).physical_events[0]
    enriched = policy.identify((third, second, first)).physical_events[0]

    assert enriched.physical_event_id == established.physical_event_id
    assert len(enriched.observations) == 3


def test_physical_event_id_ignores_geometry_updates_and_earlier_observation_keys() -> (
    None
):
    first = _event(
        _source("usgs-earthquakes"),
        event_id="usgs:stable",
        geometry=point_event_geometry(35.0, 139.0, _source("usgs-earthquakes")),
    )
    second = _event(
        _source("emsc-earthquakes"),
        event_id="emsc:stable",
        event_time=NOW - timedelta(seconds=20),
    )
    policy = DefaultEventPolicy()
    established = policy.identify((first, second)).physical_events[0]

    geometry_update = replace(
        first,
        geometry=point_event_geometry(36.0, 140.0, first.source),
    )
    updated = policy.identify((geometry_update, second)).physical_events[0]
    assert updated.physical_event_id == established.physical_event_id

    earlier = None
    for index in range(100):
        candidate = _event(
            _source(f"a-corroboration-{index:03d}"),
            event_id=f"a-corroboration:{index:03d}",
            event_time=NOW - timedelta(seconds=5),
        )
        if event_observation_key(candidate) < min(
            event_observation_key(first), event_observation_key(second)
        ):
            earlier = candidate
            break
    assert earlier is not None
    enriched = policy.identify((earlier, first, second)).physical_events[0]
    assert enriched.physical_event_id == established.physical_event_id
