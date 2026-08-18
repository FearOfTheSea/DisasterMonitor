"""Hazard-owned policies for correlating situation reports to events."""

from typing import Protocol

from disaster_monitor.application.services.evidence_reconciliation import (
    correlate_situation_report,
    correlation_signals,
)
from disaster_monitor.domain.disaster import (
    CorrelationStatus,
    DisasterEvent,
    Hazard,
    SituationReport,
)


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
        magnitude_matches = (
            report.magnitude is not None
            and event.magnitude is not None
            and abs(report.magnitude - event.magnitude) <= 0.3
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
