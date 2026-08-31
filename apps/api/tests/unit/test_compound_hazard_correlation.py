from datetime import UTC, datetime, timedelta

from disaster_monitor.application.services.active_incidents import ActiveIncident
from disaster_monitor.application.services.event_policies import (
    ASSOCIATION_LIMITATION,
    CompoundHazardCorrelationService,
)
from disaster_monitor.domain.disaster import (
    Disaster,
    EventCoordinate,
    EventGeometry,
    EventGeometryKind,
    ProviderTier,
    SourceAuthority,
    SourceReference,
    point_event_geometry,
)

NOW = datetime(2026, 8, 20, 6, tzinfo=UTC)


def _source(source_id: str) -> SourceReference:
    return SourceReference(
        source_id=source_id,
        publisher=f"{source_id} publisher",
        title=f"{source_id} record",
        canonical_url=f"https://{source_id}.example/events",
        published_at=NOW,
        updated_at=NOW,
        retrieved_at=NOW,
        authority=SourceAuthority.SCIENTIFIC_AUTHORITY,
    )


def _incident(
    disaster: Disaster,
    event_id: str,
    *,
    event_time: datetime = NOW,
    latitude: float = 10.0,
    longitude: float = 20.0,
    geometry_kind: EventGeometryKind | None = EventGeometryKind.POINT,
    physical_event_id: str | None = None,
) -> ActiveIncident:
    source = _source(f"source-{event_id}")
    if geometry_kind is EventGeometryKind.POINT:
        geometry = point_event_geometry(latitude, longitude, source)
    elif geometry_kind is EventGeometryKind.TRACK:
        geometry = EventGeometry(
            geometry_kind,
            source,
            (
                EventCoordinate(latitude, longitude),
                EventCoordinate(latitude + 0.1, longitude + 0.1),
            ),
        )
    elif geometry_kind is EventGeometryKind.AREA:
        geometry = EventGeometry(
            geometry_kind,
            source,
            (
                EventCoordinate(latitude, longitude),
                EventCoordinate(latitude + 0.1, longitude),
                EventCoordinate(latitude, longitude + 0.1),
            ),
        )
    else:
        geometry = None
    return ActiveIncident(
        event_id=event_id,
        disaster=disaster,
        location=f"{disaster.value} location",
        event_time=event_time,
        geometry=geometry,
        measurements=(),
        provider_ids=(f"provider:{event_id}",),
        provider_tier=ProviderTier.SECONDARY,
        source_authority=source.authority,
        source=source,
        physical_event_id=physical_event_id,
        evidence_sources=(source,),
    )


def _correlate(*incidents: ActiveIncident) -> tuple:
    return CompoundHazardCorrelationService().correlate(tuple(incidents))


def test_earthquake_and_landslide_inside_both_gates_emit_one_correlation() -> None:
    earthquake = _incident(Disaster.EARTHQUAKE, "quake")
    landslide = _incident(
        Disaster.LANDSLIDE,
        "slide",
        event_time=NOW + timedelta(hours=6),
        longitude=20.5,
    )

    result = _correlate(earthquake, landslide)

    assert len(result) == 1
    correlation = result[0]
    assert correlation.rule_id == "compound-hazard:earthquake-landslide:v1"
    assert correlation.relationship == "spatiotemporal_association"
    assert correlation.first_disaster is Disaster.EARTHQUAKE
    assert correlation.second_disaster is Disaster.LANDSLIDE
    assert correlation.time_delta_seconds == 6 * 3600
    assert 50 < correlation.distance_km < 60


def test_earthquake_and_landslide_outside_spatial_gate_emit_none() -> None:
    assert (
        _correlate(
            _incident(Disaster.EARTHQUAKE, "quake"),
            _incident(
                Disaster.LANDSLIDE,
                "slide",
                event_time=NOW + timedelta(hours=1),
                longitude=22.0,
            ),
        )
        == ()
    )


def test_landslide_before_earthquake_emits_none() -> None:
    assert (
        _correlate(
            _incident(Disaster.EARTHQUAKE, "quake"),
            _incident(
                Disaster.LANDSLIDE,
                "slide",
                event_time=NOW - timedelta(seconds=1),
            ),
        )
        == ()
    )


def test_earthquake_and_landslide_beyond_72_hours_emit_none() -> None:
    assert (
        _correlate(
            _incident(Disaster.EARTHQUAKE, "quake"),
            _incident(
                Disaster.LANDSLIDE,
                "slide",
                event_time=NOW + timedelta(hours=72, seconds=1),
            ),
        )
        == ()
    )


def test_cyclone_and_flood_inside_both_gates_emit_one_correlation() -> None:
    result = _correlate(
        _incident(Disaster.TROPICAL_CYCLONE, "storm"),
        _incident(
            Disaster.FLOOD,
            "flood",
            event_time=NOW - timedelta(hours=24),
            longitude=21.0,
        ),
    )

    assert len(result) == 1
    assert result[0].rule_id == "compound-hazard:tropical-cyclone-flood:v1"
    assert result[0].time_delta_seconds == 24 * 3600


def test_cyclone_and_flood_outside_temporal_gate_emit_none() -> None:
    assert (
        _correlate(
            _incident(Disaster.TROPICAL_CYCLONE, "storm"),
            _incident(
                Disaster.FLOOD,
                "flood",
                event_time=NOW - timedelta(hours=72, seconds=1),
            ),
        )
        == ()
    )


def test_cyclone_and_flood_outside_spatial_gate_emit_none() -> None:
    assert (
        _correlate(
            _incident(Disaster.TROPICAL_CYCLONE, "storm"),
            _incident(Disaster.FLOOD, "flood", longitude=23.0),
        )
        == ()
    )


def test_unsupported_pair_missing_geometry_and_non_point_geometry_emit_none() -> None:
    assert (
        _correlate(
            _incident(Disaster.EARTHQUAKE, "quake"),
            _incident(Disaster.FLOOD, "flood"),
        )
        == ()
    )
    assert (
        _correlate(
            _incident(Disaster.EARTHQUAKE, "quake"),
            _incident(
                Disaster.LANDSLIDE,
                "missing",
                event_time=NOW + timedelta(hours=1),
                geometry_kind=None,
            ),
        )
        == ()
    )
    assert (
        _correlate(
            _incident(Disaster.EARTHQUAKE, "quake"),
            _incident(
                Disaster.LANDSLIDE,
                "area",
                event_time=NOW + timedelta(hours=1),
                geometry_kind=EventGeometryKind.AREA,
            ),
        )
        == ()
    )
    assert (
        _correlate(
            _incident(
                Disaster.TROPICAL_CYCLONE,
                "track",
                geometry_kind=EventGeometryKind.TRACK,
            ),
            _incident(Disaster.FLOOD, "flood"),
        )
        == ()
    )


def test_self_identity_cannot_correlate_even_across_hazard_labels() -> None:
    assert (
        _correlate(
            _incident(
                Disaster.EARTHQUAKE,
                "same-a",
                physical_event_id="physical-event:same",
            ),
            _incident(
                Disaster.LANDSLIDE,
                "same-b",
                event_time=NOW + timedelta(hours=1),
                physical_event_id="physical-event:same",
            ),
        )
        == ()
    )


def test_reversed_and_duplicate_inputs_have_one_stable_correlation_id() -> None:
    earthquake = _incident(
        Disaster.EARTHQUAKE,
        "quake",
        physical_event_id="physical-event:quake",
    )
    landslide = _incident(
        Disaster.LANDSLIDE,
        "slide",
        event_time=NOW + timedelta(hours=1),
        physical_event_id="physical-event:slide",
    )

    forward = _correlate(earthquake, landslide)
    reversed_result = _correlate(landslide, earthquake)
    duplicated = _correlate(earthquake, landslide, earthquake, landslide)

    assert forward[0].correlation_id == reversed_result[0].correlation_id
    assert duplicated == forward


def test_multiple_relationships_are_ordered_without_transitive_synthesis() -> None:
    quake = _incident(Disaster.EARTHQUAKE, "quake")
    slide_a = _incident(
        Disaster.LANDSLIDE,
        "slide-a",
        event_time=NOW + timedelta(hours=1),
        longitude=20.2,
    )
    slide_b = _incident(
        Disaster.LANDSLIDE,
        "slide-b",
        event_time=NOW + timedelta(hours=2),
        longitude=20.4,
    )

    first = _correlate(slide_b, quake, slide_a)
    second = _correlate(slide_a, slide_b, quake)

    assert first == second
    assert len(first) == 2
    assert [item.second_event_id for item in first] == ["slide-a", "slide-b"]
    assert all(item.first_event_id == "quake" for item in first)


def test_source_ids_summary_and_non_causation_limitation_are_retained() -> None:
    result = _correlate(
        _incident(Disaster.TROPICAL_CYCLONE, "storm"),
        _incident(Disaster.FLOOD, "flood", event_time=NOW + timedelta(hours=2)),
    )

    assert result[0].source_ids == ("source-flood", "source-storm")
    assert "Tropical cyclone" in result[0].summary
    assert "flood" in result[0].summary
    assert result[0].limitation == ASSOCIATION_LIMITATION
    assert "causation" in result[0].limitation
