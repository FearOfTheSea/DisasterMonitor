from datetime import UTC, datetime

import pytest

from disaster_monitor.application.services.event_resolution import (
    default_event_policy_registry,
)
from disaster_monitor.application.services.evidence_state import (
    build_evidence_world_state,
)
from disaster_monitor.application.services.incident_priority import (
    IncidentPriorityRanker,
)
from disaster_monitor.application.services.incident_priority_policy import (
    EarthquakeIncidentPriorityPolicy,
    IncidentPriorityContribution,
    default_incident_priority_policy_registry,
)
from disaster_monitor.domain.disaster import (
    Disaster,
    DisasterEvent,
    EventMeasurement,
    FactStatus,
    IncidentPriority,
    MeasurementKind,
    ReportedFact,
    SituationReport,
    SourceReference,
    point_event_geometry,
)
from disaster_monitor.infrastructure.geography.static_country_catalog import (
    StaticCountryCatalog,
)

NOW = datetime(2026, 8, 11, 12, tzinfo=UTC)
COUNTRY = StaticCountryCatalog().get_by_alpha3("JPN")
assert COUNTRY is not None


def _source(source_id: str) -> SourceReference:
    return SourceReference(
        source_id=source_id,
        publisher="Test source",
        title="Test event",
        canonical_url=f"https://example.test/{source_id}",
        published_at=NOW,
        updated_at=NOW,
        retrieved_at=NOW,
    )


def _event(
    disaster: Disaster = Disaster.EARTHQUAKE,
    measurements: tuple[EventMeasurement, ...] = (),
) -> DisasterEvent:
    source = _source(f"event-{disaster.value}")
    return DisasterEvent(
        event_id=f"event-{disaster.value}",
        disaster=disaster,
        location=COUNTRY.canonical_name,
        country=COUNTRY,
        event_time=NOW,
        source=source,
        geometry=point_event_geometry(35.0, 139.0, source),
        measurements=measurements,
    )


def _measurement(kind: MeasurementKind, value: float | str) -> EventMeasurement:
    return EventMeasurement(kind, value, source=_source(f"measurement-{kind.value}"))


def _state(event: DisasterEvent, reports: tuple[SituationReport, ...] = ()):
    identity = (
        default_event_policy_registry().for_disaster(event.disaster).identify((event,))
    )
    return build_evidence_world_state(
        event,
        reports,
        evaluated_at=NOW,
        physical_event=identity.physical_events[0],
    )


@pytest.mark.parametrize(
    ("kind", "value", "rule_id", "score_delta", "floor"),
    (
        (
            MeasurementKind.MAGNITUDE,
            7.0,
            "tr.priority.earthquake_magnitude_critical",
            55,
            IncidentPriority.CRITICAL,
        ),
        (
            MeasurementKind.MAGNITUDE,
            6.0,
            "tr.priority.earthquake_magnitude_high",
            38,
            IncidentPriority.HIGH,
        ),
        (
            MeasurementKind.MAGNITUDE,
            5.0,
            "tr.priority.earthquake_magnitude_moderate",
            22,
            IncidentPriority.MODERATE,
        ),
        (
            MeasurementKind.MAGNITUDE,
            4.0,
            "tr.priority.earthquake_magnitude_observed",
            10,
            IncidentPriority.LOW,
        ),
        (
            MeasurementKind.INTENSITY,
            "MMI 7",
            "tr.priority.intensity_critical",
            55,
            IncidentPriority.CRITICAL,
        ),
        (
            MeasurementKind.INTENSITY,
            "MMI 6+",
            "tr.priority.intensity_high",
            40,
            IncidentPriority.HIGH,
        ),
        (
            MeasurementKind.PROVIDER_SIGNIFICANCE,
            1000.0,
            "tr.priority.provider_significance_critical",
            50,
            IncidentPriority.CRITICAL,
        ),
        (
            MeasurementKind.PROVIDER_SIGNIFICANCE,
            600.0,
            "tr.priority.provider_significance_high",
            35,
            IncidentPriority.HIGH,
        ),
        (
            MeasurementKind.PROVIDER_SIGNIFICANCE,
            300.0,
            "tr.priority.provider_significance_moderate",
            20,
            IncidentPriority.MODERATE,
        ),
    ),
)
def test_earthquake_event_severity_contributions_preserve_existing_rules(
    kind: MeasurementKind,
    value: float | str,
    rule_id: str,
    score_delta: int,
    floor: IncidentPriority,
) -> None:
    contribution = EarthquakeIncidentPriorityPolicy().event_signals(
        _event(measurements=(_measurement(kind, value),))
    )

    assert len(contribution) == 1
    assert contribution[0].rule_id == rule_id
    assert contribution[0].score_delta == score_delta
    assert contribution[0].priority_floor is floor


@pytest.mark.parametrize(
    ("value", "expected_rule"),
    (
        (3.99, None),
        (4.0, "tr.priority.earthquake_magnitude_observed"),
        (4.99, "tr.priority.earthquake_magnitude_observed"),
        (5.0, "tr.priority.earthquake_magnitude_moderate"),
        (5.99, "tr.priority.earthquake_magnitude_moderate"),
        (6.0, "tr.priority.earthquake_magnitude_high"),
        (6.99, "tr.priority.earthquake_magnitude_high"),
        (7.0, "tr.priority.earthquake_magnitude_critical"),
    ),
)
def test_magnitude_threshold_boundaries_are_closed_at_reviewed_values(
    value: float, expected_rule: str | None
) -> None:
    contributions = EarthquakeIncidentPriorityPolicy().event_signals(
        _event(measurements=(_measurement(MeasurementKind.MAGNITUDE, value),))
    )

    assert tuple(item.rule_id for item in contributions) == (
        (expected_rule,) if expected_rule is not None else ()
    )


@pytest.mark.parametrize(
    ("value", "expected_rule"),
    (
        (299.99, None),
        (300.0, "tr.priority.provider_significance_moderate"),
        (599.99, "tr.priority.provider_significance_moderate"),
        (600.0, "tr.priority.provider_significance_high"),
        (999.99, "tr.priority.provider_significance_high"),
        (1000.0, "tr.priority.provider_significance_critical"),
    ),
)
def test_provider_significance_threshold_boundaries_are_closed_at_reviewed_values(
    value: float, expected_rule: str | None
) -> None:
    contributions = EarthquakeIncidentPriorityPolicy().event_signals(
        _event(
            measurements=(_measurement(MeasurementKind.PROVIDER_SIGNIFICANCE, value),)
        )
    )

    assert tuple(item.rule_id for item in contributions) == (
        (expected_rule,) if expected_rule is not None else ()
    )


@pytest.mark.parametrize(
    "value", ("MMI 5.9", "MMI 6-", "MMI 8", "MMI 17", "7", "MMI 6 text")
)
def test_malformed_or_unrecognized_intensity_fails_closed(value: str) -> None:
    contributions = EarthquakeIncidentPriorityPolicy().event_signals(
        _event(measurements=(_measurement(MeasurementKind.INTENSITY, value),))
    )

    assert contributions == ()


@pytest.mark.parametrize("value", ("MMI 6", "MMI 6+"))
def test_reviewed_high_intensity_forms_are_admitted(value: str) -> None:
    contributions = EarthquakeIncidentPriorityPolicy().event_signals(
        _event(measurements=(_measurement(MeasurementKind.INTENSITY, value),))
    )

    assert contributions[0].rule_id == "tr.priority.intensity_high"


def test_injected_priority_registry_is_used_once_for_exact_disaster() -> None:
    calls: list[Disaster] = []
    event_calls: list[DisasterEvent] = []

    class FakePolicy:
        def event_signals(self, event: DisasterEvent):
            event_calls.append(event)
            return (
                IncidentPriorityContribution(
                    "test.priority.flood_contribution",
                    "Injected flood contribution.",
                    13,
                    priority_floor=IncidentPriority.MODERATE,
                ),
            )

    class FakeRegistry:
        def for_disaster(self, disaster: Disaster):
            calls.append(disaster)
            return FakePolicy()

    event = _event(Disaster.FLOOD)
    report_source = _source("flood-report")
    report = SituationReport(
        source=report_source,
        narrative="Two fatalities were reported.",
        facts=(
            ReportedFact(
                category="fatalities",
                label="Fatalities",
                value="2",
                status=FactStatus.CONFIRMED,
                source=report_source,
                event_id=event.event_id,
                claim_id="fatalities",
            ),
        ),
        event_id=event.event_id,
        disaster=Disaster.FLOOD,
        country_codes=(COUNTRY.alpha3_code,),
    )
    ranker = IncidentPriorityRanker(
        policy_registry=FakeRegistry(),  # type: ignore[arg-type]
    )

    assessment = ranker.assess(_state(event, (report,)))

    assert calls == [Disaster.FLOOD]
    assert event_calls == [event]
    matching = [
        signal
        for signal in assessment.signals
        if signal.rule_id == "test.priority.flood_contribution"
    ]
    assert len(matching) == 1
    assert assessment.score >= 13
    assert any(
        signal.rule_id == "tr.priority.verified_fatalities"
        for signal in assessment.signals
    )


@pytest.mark.parametrize(
    "disaster", tuple(item for item in Disaster if item is not Disaster.EARTHQUAKE)
)
def test_non_earthquake_events_do_not_activate_earthquake_severity_policy(
    disaster: Disaster,
) -> None:
    event = _event(
        disaster,
        (
            _measurement(MeasurementKind.MAGNITUDE, 7.0),
            _measurement(MeasurementKind.INTENSITY, "MMI 7"),
            _measurement(MeasurementKind.PROVIDER_SIGNIFICANCE, 1000.0),
        ),
    )
    state = _state(event)
    assessment = IncidentPriorityRanker().assess(state)

    assert (
        default_incident_priority_policy_registry()
        .for_disaster(disaster)
        .event_signals(event)
        == ()
    )
    assert assessment.score == 0
    assert assessment.signals == ()


def test_generic_human_and_operational_evidence_is_disaster_neutral() -> None:
    results = []
    for disaster in Disaster:
        event = _event(disaster)
        report_source = _source(f"report-{disaster.value}")
        report = SituationReport(
            source=report_source,
            narrative="Verified impact report.",
            facts=(
                ReportedFact(
                    category="fatalities",
                    label="Fatalities",
                    value="2",
                    status=FactStatus.CONFIRMED,
                    source=report_source,
                    event_id=event.event_id,
                    claim_id="fatalities",
                ),
                ReportedFact(
                    category="infrastructure",
                    label="Infrastructure",
                    value="Power outage",
                    status=FactStatus.CONFIRMED,
                    source=report_source,
                    event_id=event.event_id,
                    claim_id="infrastructure",
                ),
            ),
            event_id=event.event_id,
            disaster=disaster,
            country_codes=(COUNTRY.alpha3_code,),
        )
        assessment = IncidentPriorityRanker().assess(_state(event, (report,)))
        results.append(
            (
                assessment.score,
                assessment.priority,
                tuple(signal.rule_id for signal in assessment.signals),
            )
        )

    assert len(set(results)) == 1


def test_priority_policy_registry_has_a_safe_policy_for_every_disaster() -> None:
    registry = default_incident_priority_policy_registry()

    assert all(registry.for_disaster(disaster) is not None for disaster in Disaster)
