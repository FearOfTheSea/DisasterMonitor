"""Typed decision-support artifacts with explicit epistemic boundaries."""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class DecisionStatementType(StrEnum):
    VERIFIED_FACT = "verified_fact"
    ESTIMATE = "estimate"
    ASSUMPTION = "assumption"
    OPTION = "option"


class DecisionConsequence(StrEnum):
    LOW = "low"
    MODERATE = "moderate"
    HIGH = "high"


class DecisionScenarioMode(StrEnum):
    MATERIAL_HUMAN_IMPACT = "material_human_impact"
    LIMITED_OBSERVED_HUMAN_IMPACT = "limited_observed_human_impact"
    UNRESOLVED = "unresolved"


class DecisionRecommendationStatus(StrEnum):
    AVAILABLE = "available"
    DISABLED_UNSUPPORTED_PREMISE = "disabled_unsupported_premise"
    HUMAN_REVIEW_REQUIRED = "human_review_required"


class DecisionAutonomyMode(StrEnum):
    AUTONOMOUS_INTERNAL = "autonomous_internal"
    ADVISORY_ONLY = "advisory_only"


class DecisionInternalAction(StrEnum):
    NONE = "none"
    CONTINUE_APPROVED_MONITORING = "continue_approved_monitoring"
    PRIORITIZE_EVIDENCE_GAPS = "prioritize_evidence_gaps"
    COMPARE_VERIFIED_UPDATES = "compare_verified_updates"


PROHIBITED_CONSEQUENTIAL_ACTIONS = (
    "public_warning",
    "evacuation_directive",
    "resource_allocation_order",
)


@dataclass(frozen=True, slots=True)
class DecisionFact:
    fact_id: str
    statement: str
    evidence_ids: tuple[str, ...]
    source_ids: tuple[str, ...]
    status: str
    statement_type: DecisionStatementType = DecisionStatementType.VERIFIED_FACT

    def __post_init__(self) -> None:
        if not self.fact_id or not self.statement.strip():
            raise ValueError("Decision facts require stable identity and content.")
        if not self.evidence_ids or not self.source_ids:
            raise ValueError("Decision facts require evidence and source lineage.")


@dataclass(frozen=True, slots=True)
class DecisionEstimate:
    estimate_id: str
    proposition: str
    probability: float
    supporting_evidence_ids: tuple[str, ...]
    contradicting_evidence_ids: tuple[str, ...]
    statement_type: DecisionStatementType = DecisionStatementType.ESTIMATE

    def __post_init__(self) -> None:
        if not self.estimate_id or not self.proposition.strip():
            raise ValueError("Decision estimates require stable identity and content.")
        if not 0 <= self.probability <= 1:
            raise ValueError("Decision estimate probability must be bounded.")


@dataclass(frozen=True, slots=True)
class DecisionAssumption:
    assumption_id: str
    statement: str
    sensitivity: str
    evidence_gap: str
    statement_type: DecisionStatementType = DecisionStatementType.ASSUMPTION

    def __post_init__(self) -> None:
        if not all(
            value.strip()
            for value in (
                self.assumption_id,
                self.statement,
                self.sensitivity,
                self.evidence_gap,
            )
        ):
            raise ValueError(
                "Decision assumptions require explicit sensitivity and gap."
            )


@dataclass(frozen=True, slots=True)
class DecisionOption:
    option_id: str
    option_kind: str
    title: str
    description: str
    supporting_fact_ids: tuple[str, ...]
    supporting_estimate_ids: tuple[str, ...]
    assumption_ids: tuple[str, ...]
    trade_offs: tuple[str, ...]
    uncertainties: tuple[str, ...]
    consequence: DecisionConsequence
    reversible: bool
    requires_human_approval: bool
    prohibited_actions: tuple[str, ...]
    statement_type: DecisionStatementType = DecisionStatementType.OPTION

    def __post_init__(self) -> None:
        if not all(
            value.strip()
            for value in (
                self.option_id,
                self.option_kind,
                self.title,
                self.description,
            )
        ):
            raise ValueError("Decision options require stable identity and content.")
        if not (
            self.supporting_fact_ids
            or self.supporting_estimate_ids
            or self.assumption_ids
        ):
            raise ValueError("Every decision option requires traceable support.")
        if not self.trade_offs or not self.uncertainties:
            raise ValueError("Decision options require trade-offs and uncertainty.")
        if not self.prohibited_actions:
            raise ValueError("Decision options require explicit authority constraints.")


@dataclass(frozen=True, slots=True)
class DecisionContradiction:
    contradiction_id: str
    claim_key: str
    evidence_ids: tuple[str, ...]
    detail: str

    def __post_init__(self) -> None:
        if not self.contradiction_id or not self.claim_key or not self.evidence_ids:
            raise ValueError("Decision contradictions require complete lineage.")
        if not self.detail.strip():
            raise ValueError("Decision contradictions require visible detail.")


@dataclass(frozen=True, slots=True)
class DecisionScenario:
    scenario_id: str
    mode: DecisionScenarioMode
    title: str
    description: str
    probability: float
    supporting_fact_ids: tuple[str, ...]
    supporting_estimate_ids: tuple[str, ...]
    assumption_ids: tuple[str, ...]
    trade_offs: tuple[str, ...]
    sensitivity: tuple[str, ...]
    evidence_gaps: tuple[str, ...]
    policy_constraints: tuple[str, ...]

    def __post_init__(self) -> None:
        if not all((self.scenario_id, self.title.strip(), self.description.strip())):
            raise ValueError("Decision scenarios require stable identity and content.")
        if not 0 <= self.probability <= 1:
            raise ValueError("Decision scenario probability must be bounded.")
        if not self.supporting_estimate_ids:
            raise ValueError("Decision scenarios require typed estimate lineage.")
        if not self.trade_offs or not self.sensitivity:
            raise ValueError("Decision scenarios require trade-offs and sensitivity.")
        if not self.policy_constraints:
            raise ValueError("Decision scenarios require explicit policy constraints.")


@dataclass(frozen=True, slots=True)
class DecisionRecommendation:
    status: DecisionRecommendationStatus
    option_id: str | None
    confidence: float | None
    premise_fact_ids: tuple[str, ...]
    premise_estimate_ids: tuple[str, ...]
    unsupported_premise_ids: tuple[str, ...]
    rationale: str
    sensitivity: tuple[str, ...]
    evidence_gaps: tuple[str, ...]
    policy_constraints: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.rationale.strip() or not self.sensitivity:
            raise ValueError("Recommendation state requires rationale and sensitivity.")
        if not self.policy_constraints:
            raise ValueError("Recommendation state requires policy constraints.")
        if self.status == DecisionRecommendationStatus.AVAILABLE:
            if self.option_id is None or self.confidence is None:
                raise ValueError(
                    "Available recommendation requires option and confidence."
                )
            if not 0 <= self.confidence <= 1:
                raise ValueError("Recommendation confidence must be bounded.")
            if not (self.premise_fact_ids or self.premise_estimate_ids):
                raise ValueError(
                    "Available recommendation requires supported premises."
                )
            if self.unsupported_premise_ids:
                raise ValueError(
                    "High-confidence recommendation cannot depend on an "
                    "unsupported premise."
                )
        elif self.option_id is not None or self.confidence is not None:
            raise ValueError("Disabled recommendation cannot select an option.")
        if (
            self.status == DecisionRecommendationStatus.DISABLED_UNSUPPORTED_PREMISE
            and not self.unsupported_premise_ids
        ):
            raise ValueError(
                "Unsupported-premise disablement requires visible premises."
            )


@dataclass(frozen=True, slots=True)
class DecisionScenarioAnalysis:
    analysis_id: str
    evidence_state_version: str
    scenarios: tuple[DecisionScenario, ...]
    mode: DecisionScenarioMode
    assumption_sensitivity: tuple[str, ...]
    evidence_gaps: tuple[str, ...]
    recommendation: DecisionRecommendation

    def __post_init__(self) -> None:
        if not self.analysis_id or not self.evidence_state_version:
            raise ValueError("Scenario analysis requires canonical state lineage.")
        if len(self.scenarios) != 2:
            raise ValueError("Scenario analysis requires paired counterfactuals.")
        if not self.assumption_sensitivity:
            raise ValueError("Scenario analysis requires visible sensitivity.")


@dataclass(frozen=True, slots=True)
class DecisionExecutionState:
    artifact_id: str
    revision: int = 0
    monitoring_active: bool = False
    evidence_gap_priority_active: bool = False
    verified_update_comparison_active: bool = False
    public_warning_issued: bool = False
    evacuation_directive_issued: bool = False
    resource_allocation_ordered: bool = False

    def __post_init__(self) -> None:
        if not self.artifact_id or self.revision < 0:
            raise ValueError("Decision execution state requires identity and revision.")
        if (
            self.public_warning_issued
            or self.evacuation_directive_issued
            or self.resource_allocation_ordered
        ):
            raise ValueError(
                "Decision autonomy cannot represent prohibited consequential effects."
            )


@dataclass(frozen=True, slots=True)
class DecisionExecutionOutcome:
    execution_id: str
    artifact_id: str
    autonomy_mode: DecisionAutonomyMode
    action: DecisionInternalAction
    selected_option_id: str | None
    initial_state: DecisionExecutionState
    final_state: DecisionExecutionState
    reversible: bool
    requires_human_intervention: bool
    policy_rule_ids: tuple[str, ...]
    termination_reason: str

    def __post_init__(self) -> None:
        if not self.execution_id or not self.artifact_id:
            raise ValueError("Decision execution requires stable artifact lineage.")
        if (
            self.initial_state.artifact_id != self.artifact_id
            or self.final_state.artifact_id != self.artifact_id
        ):
            raise ValueError("Decision execution state escaped artifact lineage.")
        if not self.policy_rule_ids or not self.termination_reason:
            raise ValueError(
                "Decision execution requires policy and termination state."
            )
        if self.autonomy_mode == DecisionAutonomyMode.AUTONOMOUS_INTERNAL:
            if (
                self.action == DecisionInternalAction.NONE
                or self.selected_option_id is None
                or not self.reversible
                or self.requires_human_intervention
                or self.final_state.revision != self.initial_state.revision + 1
            ):
                raise ValueError(
                    "Autonomous decision must be reversible internal state change."
                )
        elif (
            self.action != DecisionInternalAction.NONE
            or self.selected_option_id is not None
            or self.final_state != self.initial_state
        ):
            raise ValueError("Advisory-only decision cannot change system state.")


@dataclass(frozen=True, slots=True)
class DecisionSupportArtifact:
    artifact_id: str
    physical_event_id: str
    evidence_state_version: str
    priority_assessment_id: str
    triage_decision_id: str
    facts: tuple[DecisionFact, ...]
    estimates: tuple[DecisionEstimate, ...]
    assumptions: tuple[DecisionAssumption, ...]
    options: tuple[DecisionOption, ...]
    contradictions: tuple[DecisionContradiction, ...]
    evidence_gaps: tuple[str, ...]
    scenario_analysis: DecisionScenarioAnalysis
    generated_at: datetime
    advisory_only: bool = True

    def __post_init__(self) -> None:
        if not all(
            (
                self.artifact_id,
                self.physical_event_id,
                self.evidence_state_version,
                self.priority_assessment_id,
                self.triage_decision_id,
            )
        ):
            raise ValueError("Decision support requires complete state lineage.")
        if not self.facts or not self.assumptions or not self.options:
            raise ValueError(
                "Decision support requires facts, assumptions, and options."
            )
        if not self.advisory_only:
            raise ValueError("Decision support is advisory-only at this milestone.")
