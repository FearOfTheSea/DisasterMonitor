"""Hypothesis and bounded internal-triage domain records."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from disaster_monitor.domain.evidence_types import HypothesisTruthStatus


class IncidentPriority(StrEnum):
    """Internal attention class derived from verified evidence state."""

    LOW = "low"
    MODERATE = "moderate"
    HIGH = "high"
    CRITICAL = "critical"


class TriageAutonomyMode(StrEnum):
    """Authority mode for one reversible internal triage decision."""

    AUTONOMOUS_INTERNAL = "autonomous_internal"
    HUMAN_ON_THE_LOOP = "human_on_the_loop"
    HUMAN_IN_THE_LOOP = "human_in_the_loop"


class InternalTriageAction(StrEnum):
    """Closed set of internal-only actions; suppression is deliberately absent."""

    MONITOR_INTERNAL = "monitor_internal"
    QUEUE_INTERNAL = "queue_internal"
    REQUEST_PRIORITY_REVIEW = "request_priority_review"
    ESCALATE_CRITICAL = "escalate_critical"


@dataclass(frozen=True, slots=True)
class HypothesisFeature:
    """Public rule contribution; this is audit metadata, not chain-of-thought."""

    rule_id: str
    description: str
    contribution: float


@dataclass(frozen=True, slots=True)
class HypothesisArtifact:
    """A deterministic inferred product kept structurally apart from observations."""

    hypothesis_id: str
    proposition: str
    probability: float
    supporting_evidence_ids: tuple[str, ...]
    contradicting_evidence_ids: tuple[str, ...]
    evaluated_at: datetime
    state_version: str
    rationale_features: tuple[HypothesisFeature, ...]
    uncertain_evidence_ids: tuple[str, ...] = ()
    truth_status: HypothesisTruthStatus = HypothesisTruthStatus.INFERRED

    def __post_init__(self) -> None:
        if not 0.0 <= self.probability <= 1.0:
            raise ValueError("Hypothesis probability must be between zero and one.")


@dataclass(frozen=True, slots=True)
class IncidentPrioritySignal:
    """Public policy contribution with direct evidence lineage where applicable."""

    rule_id: str
    detail: str
    score_delta: int
    evidence_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.rule_id.strip() or not self.detail.strip():
            raise ValueError("Priority signals require a rule ID and public detail.")
        if self.score_delta < 0:
            raise ValueError("Uncertainty and evidence cannot reduce priority score.")


@dataclass(frozen=True, slots=True)
class IncidentPriorityAssessment:
    """Deterministic internal ranking result tied to one canonical EW version."""

    assessment_id: str
    physical_event_id: str
    evidence_state_version: str
    priority: IncidentPriority
    score: int
    requires_human_review: bool
    uncertainty_escalated: bool
    signals: tuple[IncidentPrioritySignal, ...]
    assessed_at: datetime

    def __post_init__(self) -> None:
        if not self.assessment_id or not self.physical_event_id:
            raise ValueError("Priority assessments require stable event lineage.")
        if not self.evidence_state_version:
            raise ValueError("Priority assessments require an EW state version.")
        if not 0 <= self.score <= 100:
            raise ValueError("Priority score must be between zero and one hundred.")

    @property
    def is_critical(self) -> bool:
        return self.priority == IncidentPriority.CRITICAL


@dataclass(frozen=True, slots=True)
class InternalTriageDecision:
    """Bounded triage action that cannot create an external operational effect."""

    decision_id: str
    assessment_id: str
    physical_event_id: str
    evidence_state_version: str
    priority: IncidentPriority
    action: InternalTriageAction
    autonomy_mode: TriageAutonomyMode
    reversible: bool
    requires_human_intervention: bool
    policy_rule_ids: tuple[str, ...]
    decided_at: datetime

    def __post_init__(self) -> None:
        if not self.decision_id or not self.assessment_id:
            raise ValueError("Triage decisions require assessment lineage.")
        if not self.physical_event_id or not self.evidence_state_version:
            raise ValueError("Triage decisions require event and EW lineage.")
        if not self.policy_rule_ids:
            raise ValueError("Triage decisions require machine-testable policy rules.")
        if self.autonomy_mode == TriageAutonomyMode.AUTONOMOUS_INTERNAL:
            if self.priority not in {IncidentPriority.LOW, IncidentPriority.MODERATE}:
                raise ValueError(
                    "Autonomous triage is limited to low/moderate priority."
                )
            if self.action not in {
                InternalTriageAction.MONITOR_INTERNAL,
                InternalTriageAction.QUEUE_INTERNAL,
            }:
                raise ValueError("Autonomous triage actions must remain internal.")
            if not self.reversible or self.requires_human_intervention:
                raise ValueError(
                    "Autonomous internal triage must be reversible and "
                    "intervention-free."
                )
        if self.priority == IncidentPriority.CRITICAL and (
            self.action != InternalTriageAction.ESCALATE_CRITICAL
            or self.autonomy_mode != TriageAutonomyMode.HUMAN_IN_THE_LOOP
            or not self.requires_human_intervention
        ):
            raise ValueError("Critical incidents require human-in-the-loop escalation.")
