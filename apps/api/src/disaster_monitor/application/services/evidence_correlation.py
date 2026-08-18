"""Application-owned, hazard-selectable situation/event correlation policies."""

import re
from dataclasses import dataclass
from typing import Protocol

from disaster_monitor.domain.disaster import (
    CorrelationStatus,
    DisasterEvent,
    Hazard,
    MeasurementKind,
    SituationReport,
)


@dataclass(frozen=True, slots=True)
class CorrelationSignals:
    date_matches: bool
    location_matches: bool
    country_matches: bool


def correlation_signals(
    report: SituationReport, event: DisasterEvent
) -> CorrelationSignals:
    if report.reported_event_time is not None:
        time_delta = abs(
            (report.reported_event_time - event.event_time).total_seconds()
        )
        date_matches = time_delta <= 48 * 60 * 60
    else:
        date_matches = False
    source_text = " ".join(
        (report.source.title, report.narrative, *report.locations, *report.countries)
    ).lower()
    ignored_location_words = {
        "near",
        "prefecture",
        "island",
        *re.findall(r"[a-z][a-z-]{1,}", event.country.canonical_name.lower()),
        *(alias.lower() for alias in event.country.aliases),
    }
    event_location_words = {
        word
        for word in re.findall(r"[a-z][a-z-]{2,}", event.location.lower())
        if word not in ignored_location_words
    }
    location_matches = bool(
        event_location_words
        and any(word in source_text for word in event_location_words)
    )
    country_terms = {
        event.country.alpha3_code.lower(),
        event.country.canonical_name.lower(),
        *(alias.lower() for alias in event.country.aliases),
    }
    country_matches = bool(
        {country.lower() for country in report.countries} & country_terms
    )
    return CorrelationSignals(date_matches, location_matches, country_matches)


def correlate_situation_report(
    report: SituationReport, event: DisasterEvent
) -> CorrelationStatus:
    """Apply only hazard-neutral correlation signals."""
    event_ids = {event.event_id.lower(), *(item.lower() for item in event.provider_ids)}
    report_ids = {
        item.lower() for item in (report.event_id, *report.provider_event_ids) if item
    }
    comparable_pairs = {
        (report_id, event_id)
        for report_id in report_ids
        for event_id in event_ids
        if _identifier_namespace(report_id) == _identifier_namespace(event_id)
    }
    if any(report_id == event_id for report_id, event_id in comparable_pairs):
        return CorrelationStatus.MATCHED
    if comparable_pairs:
        return CorrelationStatus.UNMATCHED
    if report.hazard is not None and report.hazard != event.hazard:
        return CorrelationStatus.UNMATCHED
    if report.country_codes and event.country.alpha3_code not in {
        code.upper() for code in report.country_codes
    }:
        return CorrelationStatus.UNMATCHED
    signals = correlation_signals(report, event)
    if signals.date_matches and signals.location_matches:
        return CorrelationStatus.MATCHED
    if (signals.date_matches and signals.country_matches) or signals.location_matches:
        return CorrelationStatus.POSSIBLE
    return CorrelationStatus.UNMATCHED


def _identifier_namespace(identifier: str) -> str:
    prefix, separator, _ = identifier.partition(":")
    return prefix if separator else "unqualified"


class EvidenceCorrelationPolicy(Protocol):
    def correlate(
        self, report: SituationReport, event: DisasterEvent
    ) -> CorrelationStatus: ...


class DefaultEvidenceCorrelationPolicy:
    def correlate(
        self, report: SituationReport, event: DisasterEvent
    ) -> CorrelationStatus:
        return correlate_situation_report(report, event)


class EarthquakeEvidenceCorrelationPolicy(DefaultEvidenceCorrelationPolicy):
    """Retain earthquake measurement matching outside generic reconciliation."""

    def correlate(
        self, report: SituationReport, event: DisasterEvent
    ) -> CorrelationStatus:
        neutral = super().correlate(report, event)
        if (
            neutral != CorrelationStatus.POSSIBLE
            and neutral != CorrelationStatus.UNMATCHED
        ):
            return neutral
        signals = correlation_signals(report, event)
        event_measurement = event.measurement(MeasurementKind.MAGNITUDE)
        report_measurement = next(
            (
                measurement
                for measurement in report.measurements
                if measurement.kind is MeasurementKind.MAGNITUDE
            ),
            None,
        )
        magnitude = (
            event_measurement.value
            if event_measurement is not None
            and isinstance(event_measurement.value, (int, float))
            else None
        )
        report_magnitude = (
            report_measurement.value
            if report_measurement is not None
            and isinstance(report_measurement.value, (int, float))
            else None
        )
        magnitude_matches = (
            report_magnitude is not None
            and magnitude is not None
            and abs(report_magnitude - magnitude) <= 0.3
        )
        if magnitude_matches and signals.location_matches:
            return CorrelationStatus.MATCHED
        if signals.date_matches and magnitude_matches:
            return CorrelationStatus.POSSIBLE
        return neutral


class EvidenceCorrelationPolicies:
    def __init__(self, policies: dict[Hazard, EvidenceCorrelationPolicy]) -> None:
        self._policies = dict(policies)
        self._default = DefaultEvidenceCorrelationPolicy()

    def for_hazard(self, hazard: Hazard) -> EvidenceCorrelationPolicy:
        return self._policies.get(hazard, self._default)


def default_evidence_correlation_policies() -> EvidenceCorrelationPolicies:
    return EvidenceCorrelationPolicies(
        {Hazard.EARTHQUAKE: EarthquakeEvidenceCorrelationPolicy()}
    )
