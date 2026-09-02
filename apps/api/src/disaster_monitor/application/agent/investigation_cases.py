"""Typed, user-safe artifacts for bounded two-hazard investigations."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import NAMESPACE_URL, uuid5

from disaster_monitor.application.agent.models import AgentStatus, InvestigationTarget
from disaster_monitor.application.disaster import ReportSection, SelectedEventSummary
from disaster_monitor.application.services.event_policies import (
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
    country: InvestigationCaseCountry
    targets: tuple[InvestigationTargetResult, InvestigationTargetResult]
    cross_hazard_assessment: CrossHazardAssessment
    correlations: tuple[CompoundHazardCorrelation, ...]
    status: InvestigationCaseStatus
    partial: bool

    @property
    def branch_statuses(self) -> tuple[str, str]:
        return self.targets[0].status.value, self.targets[1].status.value

    @property
    def selected_events(
        self,
    ) -> tuple[SelectedEventSummary | None, SelectedEventSummary | None]:
        return self.targets[0].selected_event, self.targets[1].selected_event

    @property
    def physical_event_ids(self) -> tuple[str | None, str | None]:
        return self.targets[0].physical_event_id, self.targets[1].physical_event_id

    @property
    def evidence_state_versions(self) -> tuple[str | None, str | None]:
        return (
            self.targets[0].evidence_state_version,
            self.targets[1].evidence_state_version,
        )


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


def stable_case_id(country: Country, targets: tuple[InvestigationTarget, ...]) -> str:
    material = "|".join(
        (
            country.alpha3_code,
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
    "causation_requested",
    "stable_case_id",
]
