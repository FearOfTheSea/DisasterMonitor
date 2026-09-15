"""Typed, user-safe artifacts for bounded multi-hazard investigations."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from itertools import combinations
from uuid import NAMESPACE_URL, uuid5

from disaster_monitor.application.agent.models import AgentStatus, InvestigationTarget
from disaster_monitor.application.disaster import ReportSection, SelectedEventSummary
from disaster_monitor.application.evidence.event_policies import (
    ASSOCIATION_LIMITATION,
    CompoundHazardCorrelation,
    CompoundHazardCorrelationService,
    CorrelatableIncident,
)
from disaster_monitor.domain.disaster import (
    Country,
    Disaster,
    EventGeometry,
    EventGeometryKind,
    SourceReference,
)


class InvestigationCaseStatus(StrEnum):
    COMPLETED = "completed"
    PARTIAL = "partial"


class CrossHazardAssessmentStatus(StrEnum):
    ASSOCIATED = "associated"
    NOT_ESTABLISHED = "not_established"
    UNSUPPORTED_PAIR = "unsupported_pair"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"


@dataclass(frozen=True, slots=True)
class InvestigationCaseCountry:
    """Small browser-safe country projection for a case."""

    country_code: str
    country_name: str

    @classmethod
    def from_country(cls, country: Country) -> InvestigationCaseCountry:
        return cls(country.alpha3_code, country.canonical_name)


@dataclass(frozen=True, slots=True)
class InvestigationTargetResult:
    """Safe result projection for one sequential evidence branch."""

    target: InvestigationTarget
    status: AgentStatus
    selected_event: SelectedEventSummary | None
    sources: tuple[SourceReference, ...]
    warnings: tuple[str, ...]
    sections: tuple[ReportSection, ...]
    partial: bool
    termination_reason: str
    physical_event_id: str | None = None
    evidence_state_version: str | None = None
    source_ids: tuple[str, ...] = ()
    capability_gaps: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class CrossHazardAssessment:
    status: CrossHazardAssessmentStatus
    summary: str
    limitation: str


@dataclass(frozen=True, slots=True)
class InvestigationCaseArtifact:
    """The sole persisted projection of a multi-hazard request."""

    case_id: str
    country: InvestigationCaseCountry | None
    targets: tuple[InvestigationTargetResult, ...]
    cross_hazard_assessment: CrossHazardAssessment
    correlations: tuple[CompoundHazardCorrelation, ...]
    status: InvestigationCaseStatus
    partial: bool
    countries: tuple[InvestigationCaseCountry, ...] = ()

    def __post_init__(self) -> None:
        if not self.countries and self.country is not None:
            object.__setattr__(self, "countries", (self.country,))

    @property
    def branch_statuses(self) -> tuple[str, ...]:
        return tuple(item.status.value for item in self.targets)

    @property
    def selected_events(
        self,
    ) -> tuple[SelectedEventSummary | None, ...]:
        return tuple(item.selected_event for item in self.targets)

    @property
    def physical_event_ids(self) -> tuple[str | None, ...]:
        return tuple(item.physical_event_id for item in self.targets)

    @property
    def evidence_state_versions(self) -> tuple[str | None, ...]:
        return tuple(item.evidence_state_version for item in self.targets)


@dataclass(frozen=True, slots=True)
class InvestigationCaseReport:
    """One deterministic presentation assembled from case-safe branch artifacts."""

    message: str
    sources: tuple[SourceReference, ...]
    warnings: tuple[str, ...]
    sections: tuple[ReportSection, ...]
    partial: bool


@dataclass(frozen=True, slots=True)
class InvestigationIncident:
    """Minimal correlation projection; it never promotes branch evidence."""

    event_id: str
    physical_event_id: str | None
    disaster: Disaster
    event_time: datetime
    geometry: EventGeometry | None
    source: SourceReference

    @classmethod
    def from_target_result(
        cls, result: InvestigationTargetResult
    ) -> InvestigationIncident | None:
        event = result.selected_event
        if event is None:
            return None
        return cls(
            event.event_id,
            result.physical_event_id,
            event.disaster,
            event.event_time,
            event.geometry,
            event.source,
        )


_CAUSATION_TERMS = re.compile(
    r"\b(?:cause(?:d|s|ing)?|trigger(?:ed|s|ing)?|because of|lead(?:s|ing)? to)\b",
    re.IGNORECASE,
)


def causation_requested(question: str) -> bool:
    return bool(_CAUSATION_TERMS.search(question))


def stable_case_id(
    countries: tuple[Country, ...], targets: tuple[InvestigationTarget, ...]
) -> str:
    material = "|".join(
        (
            *(country.alpha3_code for country in countries),
            *(f"{item.target_id}:{item.disaster.value}" for item in targets),
        )
    )
    return f"investigation-case:v1:{uuid5(NAMESPACE_URL, material)}"


def assess_cross_hazard_pair(
    first: CorrelatableIncident | None,
    second: CorrelatableIncident | None,
    *,
    causation_requested: bool,
) -> tuple[CrossHazardAssessment, tuple[CompoundHazardCorrelation, ...]]:
    """Apply the maintained pair rule without inferring causation or relation."""
    if first is None or second is None:
        return (
            CrossHazardAssessment(
                CrossHazardAssessmentStatus.INSUFFICIENT_EVIDENCE,
                "One or both hazards did not yield a selected source-backed event, so "
                "a cross-hazard assessment could not be completed.",
                ASSOCIATION_LIMITATION,
            ),
            (),
        )
    service = CompoundHazardCorrelationService()
    if not service.supports_pair(first.disaster, second.disaster):
        return (
            CrossHazardAssessment(
                CrossHazardAssessmentStatus.UNSUPPORTED_PAIR,
                "DisasterMonitor has no maintained cross-hazard rule for "
                f"{_hazard_pair(first.disaster, second.disaster)}.",
                ASSOCIATION_LIMITATION,
            ),
            (),
        )
    if not _usable_point_geometry(first) or not _usable_point_geometry(second):
        return (
            CrossHazardAssessment(
                CrossHazardAssessmentStatus.INSUFFICIENT_EVIDENCE,
                "The selected events lack the source-backed point geometry required "
                "by the maintained cross-hazard rule.",
                ASSOCIATION_LIMITATION,
            ),
            (),
        )
    if _identity(first) == _identity(second):
        return (
            CrossHazardAssessment(
                CrossHazardAssessmentStatus.INSUFFICIENT_EVIDENCE,
                "The selected branch events do not establish two distinct physical "
                "events for cross-hazard assessment.",
                ASSOCIATION_LIMITATION,
            ),
            (),
        )
    correlations = service.correlate((first, second))
    if correlations:
        summary = (
            "The maintained rule found a spatiotemporal association between the "
            "selected events."
        )
        if causation_requested:
            summary += " This association does not establish causation."
        return (
            CrossHazardAssessment(
                CrossHazardAssessmentStatus.ASSOCIATED,
                summary,
                ASSOCIATION_LIMITATION,
            ),
            correlations,
        )
    return (
        CrossHazardAssessment(
            CrossHazardAssessmentStatus.NOT_ESTABLISHED,
            "No association was established under the maintained cross-hazard rule.",
            ASSOCIATION_LIMITATION,
        ),
        (),
    )


def assess_cross_hazard_set(
    incidents: tuple[InvestigationIncident | None, ...],
    *,
    causation_requested: bool,
) -> tuple[CrossHazardAssessment, tuple[CompoundHazardCorrelation, ...]]:
    """Assess every non-recursive pair in a bounded set and summarize conservatively."""
    assessments: list[CrossHazardAssessment] = []
    correlations: list[CompoundHazardCorrelation] = []
    for first, second in combinations(incidents, 2):
        if (
            first is not None
            and second is not None
            and first.disaster is second.disaster
        ):
            continue
        assessment, pair_correlations = assess_cross_hazard_pair(
            first,
            second,
            causation_requested=causation_requested,
        )
        assessments.append(assessment)
        correlations.extend(pair_correlations)
    if correlations:
        summary = (
            f"Maintained rules found {len(correlations)} spatiotemporal "
            "association(s) among the selected events."
        )
        if causation_requested:
            summary += " These associations do not establish causation."
        return (
            CrossHazardAssessment(
                CrossHazardAssessmentStatus.ASSOCIATED,
                summary,
                ASSOCIATION_LIMITATION,
            ),
            tuple(correlations),
        )
    statuses = {item.status for item in assessments}
    if not assessments or CrossHazardAssessmentStatus.INSUFFICIENT_EVIDENCE in statuses:
        status = CrossHazardAssessmentStatus.INSUFFICIENT_EVIDENCE
        summary = (
            "At least one requested comparison lacked distinct, source-backed events "
            "with the geometry required by a maintained rule."
        )
    elif statuses == {CrossHazardAssessmentStatus.UNSUPPORTED_PAIR}:
        status = CrossHazardAssessmentStatus.UNSUPPORTED_PAIR
        summary = "No maintained rule covers any selected cross-hazard pair."
    else:
        status = CrossHazardAssessmentStatus.NOT_ESTABLISHED
        summary = "No association was established under the maintained rules."
    return CrossHazardAssessment(status, summary, ASSOCIATION_LIMITATION), ()


def _usable_point_geometry(incident: CorrelatableIncident) -> bool:
    geometry = incident.geometry
    return (
        geometry is not None
        and geometry.kind is EventGeometryKind.POINT
        and len(geometry.coordinates) == 1
    )


def _identity(incident: CorrelatableIncident) -> str:
    if incident.physical_event_id:
        return incident.physical_event_id.casefold()
    return f"{incident.source.source_id.casefold()}:{incident.event_id.casefold()}"


def _hazard_pair(first: Disaster, second: Disaster) -> str:
    return " and ".join(item.value.replace("_", " ") for item in (first, second))


__all__ = [
    "CrossHazardAssessment",
    "CrossHazardAssessmentStatus",
    "InvestigationCaseArtifact",
    "InvestigationCaseCountry",
    "InvestigationCaseReport",
    "InvestigationCaseStatus",
    "InvestigationIncident",
    "InvestigationTargetResult",
    "assess_cross_hazard_pair",
    "assess_cross_hazard_set",
    "causation_requested",
    "stable_case_id",
]
