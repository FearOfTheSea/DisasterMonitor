from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from disaster_monitor.application.disaster import DisasterQuery
from disaster_monitor.application.services.event_resolution import (
    DefaultEventPolicy,
)
from disaster_monitor.application.services.source_evidence_policy import (
    SourceEvidencePolicyError,
    validate_physical_event_evidence,
)
from disaster_monitor.domain.disaster import (
    DisasterEvent,
    EventMeasurement,
    Hazard,
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
    event_time: datetime = NOW,
) -> DisasterEvent:
    return DisasterEvent(
        event_id=event_id,
        hazard=Hazard.FLOOD,
        location="Japan",
        country=JAPAN,
        event_time=event_time,
        source=source,
        geometry=geometry,
        measurements=measurements,
        provider_ids=(event_id,),
    )


def _query() -> DisasterQuery:
    return DisasterQuery(Hazard.FLOOD, JAPAN, "recent", ("latest",))


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
