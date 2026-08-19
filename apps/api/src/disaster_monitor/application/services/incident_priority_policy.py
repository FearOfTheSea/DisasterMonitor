"""Disaster-owned event-severity contributions for incident prioritization."""

import re
from dataclasses import dataclass
from typing import Protocol

from disaster_monitor.domain.disaster import (
    Disaster,
    DisasterEvent,
    IncidentPriority,
    MeasurementKind,
)


@dataclass(frozen=True, slots=True)
class IncidentPriorityContribution:
    """Immutable event-severity contribution consumed by the generic ranker."""

    rule_id: str
    detail: str
    score_delta: int
    priority_floor: IncidentPriority = IncidentPriority.LOW
    evidence_ids: tuple[str, ...] = ()


class IncidentPriorityPolicy(Protocol):
    """Provide only disaster-owned event-severity contributions."""

    def event_signals(
        self, event: DisasterEvent
    ) -> tuple[IncidentPriorityContribution, ...]: ...


class DefaultIncidentPriorityPolicy:
    """Conservative policy for disasters without reviewed event-severity rules."""

    def event_signals(
        self, event: DisasterEvent
    ) -> tuple[IncidentPriorityContribution, ...]:
        return ()


class EarthquakeIncidentPriorityPolicy:
    """Reviewed USGS/earthquake event-severity rules."""

    def event_signals(
        self, event: DisasterEvent
    ) -> tuple[IncidentPriorityContribution, ...]:
        if event.disaster is not Disaster.EARTHQUAKE:
            return ()

        contributions: list[IncidentPriorityContribution] = []
        magnitude = _numeric_measurement(event, MeasurementKind.MAGNITUDE)
        if magnitude is not None:
            if magnitude >= 7:
                contributions.append(
                    IncidentPriorityContribution(
                        "tr.priority.earthquake_magnitude_critical",
                        "Verified earthquake magnitude is at least 7.0.",
                        55,
                        priority_floor=IncidentPriority.CRITICAL,
                    )
                )
            elif magnitude >= 6:
                contributions.append(
                    IncidentPriorityContribution(
                        "tr.priority.earthquake_magnitude_high",
                        "Verified earthquake magnitude is at least 6.0.",
                        38,
                        priority_floor=IncidentPriority.HIGH,
                    )
                )
            elif magnitude >= 5:
                contributions.append(
                    IncidentPriorityContribution(
                        "tr.priority.earthquake_magnitude_moderate",
                        "Verified earthquake magnitude is at least 5.0.",
                        22,
                        priority_floor=IncidentPriority.MODERATE,
                    )
                )
            elif magnitude >= 4:
                contributions.append(
                    IncidentPriorityContribution(
                        "tr.priority.earthquake_magnitude_observed",
                        "Verified earthquake magnitude is at least 4.0.",
                        10,
                    )
                )

        intensity = _intensity_level(
            _measurement_value(event, MeasurementKind.INTENSITY)
        )
        if intensity is not None and intensity >= 7:
            contributions.append(
                IncidentPriorityContribution(
                    "tr.priority.intensity_critical",
                    "Verified event intensity reached the declared critical level.",
                    55,
                    priority_floor=IncidentPriority.CRITICAL,
                )
            )
        elif intensity is not None and intensity >= 6:
            contributions.append(
                IncidentPriorityContribution(
                    "tr.priority.intensity_high",
                    "Verified event intensity reached the declared high level.",
                    40,
                    priority_floor=IncidentPriority.HIGH,
                )
            )

        significance = _numeric_measurement(
            event, MeasurementKind.PROVIDER_SIGNIFICANCE
        )
        if significance is not None:
            if significance >= 1_000:
                contributions.append(
                    IncidentPriorityContribution(
                        "tr.priority.provider_significance_critical",
                        "Verified provider significance is at least 1000.",
                        50,
                        priority_floor=IncidentPriority.CRITICAL,
                    )
                )
            elif significance >= 600:
                contributions.append(
                    IncidentPriorityContribution(
                        "tr.priority.provider_significance_high",
                        "Verified provider significance is at least 600.",
                        35,
                        priority_floor=IncidentPriority.HIGH,
                    )
                )
            elif significance >= 300:
                contributions.append(
                    IncidentPriorityContribution(
                        "tr.priority.provider_significance_moderate",
                        "Verified provider significance is at least 300.",
                        20,
                        priority_floor=IncidentPriority.MODERATE,
                    )
                )
        return tuple(contributions)


class IncidentPriorityPolicyRegistry:
    """Resolve a disaster to its reviewed event-severity policy."""

    def __init__(
        self,
        policies: dict[Disaster, IncidentPriorityPolicy],
        default: IncidentPriorityPolicy,
    ) -> None:
        self._policies = dict(policies)
        self._default = default

    def for_disaster(self, disaster: Disaster) -> IncidentPriorityPolicy:
        return self._policies.get(disaster, self._default)


def default_incident_priority_policy_registry() -> IncidentPriorityPolicyRegistry:
    """Return the registry with earthquake rules and a no-event-severity default."""
    return IncidentPriorityPolicyRegistry(
        {Disaster.EARTHQUAKE: EarthquakeIncidentPriorityPolicy()},
        DefaultIncidentPriorityPolicy(),
    )


def _measurement_value(
    event: DisasterEvent, kind: MeasurementKind
) -> float | str | None:
    measurement = event.measurement(kind)
    return measurement.value if measurement is not None else None


def _numeric_measurement(event: DisasterEvent, kind: MeasurementKind) -> float | None:
    value = _measurement_value(event, kind)
    return float(value) if isinstance(value, (int, float)) else None


def _intensity_level(value: float | str | None) -> int | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return int(value)
    match = re.search(r"[1-7]", value)
    return None if match is None else int(match.group())
