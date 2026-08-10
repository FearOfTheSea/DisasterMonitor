"""Governed offline-learning artifacts for non-authority analytical tuning."""

from dataclasses import dataclass
from enum import StrEnum


class AnalyticalFocus(StrEnum):
    EVIDENCE_GAPS = "evidence_gaps"
    MATERIAL_CONFLICTS = "material_conflicts"
    MULTIMODAL_REVIEW = "multimodal_review"
    ROUTINE_MONITORING = "routine_monitoring"


class LearningPartition(StrEnum):
    TRAIN = "train"
    DEV = "dev"
    TEST = "test"


class LearningReleaseStatus(StrEnum):
    APPROVED = "approved"
    REJECTED_SAFETY = "rejected_safety"
    REJECTED_GROUNDING = "rejected_grounding"
    REJECTED_NO_SIGNIFICANT_IMPROVEMENT = "rejected_no_significant_improvement"


class DriftType(StrEnum):
    NEW_HAZARD = "new_hazard"
    LANGUAGE = "language"
    PROVIDER_SCHEMA = "provider_schema"
    SOURCE_LATENCY = "source_latency"
    IMAGE_DOMAIN = "image_domain"


class DriftAdaptationStatus(StrEnum):
    ADAPTED = "adapted"
    NON_ADAPTIVE_SAFE_MODE = "non_adaptive_safe_mode"


class OptimizationScope(StrEnum):
    ANALYTICAL_TUNING = "analytical_tuning"
    TRUST_REGISTRY = "trust_registry"
    PERMISSIONS = "permissions"
    SAFETY_THRESHOLDS = "safety_thresholds"
    HIGH_CONSEQUENCE_AUTHORITY = "high_consequence_authority"


class OptimizationStatus(StrEnum):
    APPROVED = "approved"
    REJECTED_PROTECTED_SCOPE = "rejected_protected_scope"
    REJECTED_OUTSIDE_ALLOWLIST = "rejected_outside_allowlist"
    REJECTED_NOT_REVERSIBLE = "rejected_not_reversible"
    REJECTED_INSUFFICIENT_IMPROVEMENT = "rejected_insufficient_improvement"
    REJECTED_REGRESSION = "rejected_regression"


@dataclass(frozen=True, slots=True)
class AnalyticalTuningParameters:
    parameter_set_id: str
    evidence_gap_weight: float
    material_conflict_weight: float
    multimodal_review_weight: float
    routine_monitoring_weight: float
    attenuated_signal_boost: float = 1.0
    source_authority_mutable: bool = False
    permission_mutable: bool = False
    safety_threshold_mutable: bool = False

    def __post_init__(self) -> None:
        if not self.parameter_set_id:
            raise ValueError("Analytical tuning requires stable parameter identity.")
        if any(
            not 0.5 <= value <= 5.0
            for value in (
                self.evidence_gap_weight,
                self.material_conflict_weight,
                self.multimodal_review_weight,
                self.routine_monitoring_weight,
            )
        ):
            raise ValueError(
                "Analytical tuning weights must remain reversible and bounded."
            )
        if not 1.0 <= self.attenuated_signal_boost <= 3.0:
            raise ValueError(
                "Analytical signal boost must remain reversible and bounded."
            )
        if (
            self.source_authority_mutable
            or self.permission_mutable
            or self.safety_threshold_mutable
        ):
            raise ValueError(
                "Analytical tuning cannot mutate authority or safety policy."
            )


@dataclass(frozen=True, slots=True)
class LearningTrajectory:
    trajectory_id: str
    family: str
    partition: LearningPartition
    evidence_gap_signal: float
    material_conflict_signal: float
    multimodal_signal: float
    routine_signal: float
    gold_focus: AnalyticalFocus
    grounded: bool
    critical_safety_pass: bool
    unsafe_focuses: tuple[AnalyticalFocus, ...]
    ungrounded_focuses: tuple[AnalyticalFocus, ...]
    provenance_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.trajectory_id or not self.family or not self.provenance_ids:
            raise ValueError("Learning trajectory requires identity and provenance.")
        if any(
            not 0 <= value <= 1
            for value in (
                self.evidence_gap_signal,
                self.material_conflict_signal,
                self.multimodal_signal,
                self.routine_signal,
            )
        ):
            raise ValueError("Learning trajectory signals must be normalized.")


@dataclass(frozen=True, slots=True)
class LearningEvaluation:
    task_accuracy: float
    grounding_rate: float
    critical_safety_rate: float

    def __post_init__(self) -> None:
        if any(
            not 0 <= value <= 1
            for value in (
                self.task_accuracy,
                self.grounding_rate,
                self.critical_safety_rate,
            )
        ):
            raise ValueError("Learning evaluation metrics must be bounded.")


@dataclass(frozen=True, slots=True)
class OfflineLearningRelease:
    release_id: str
    dataset_version: str
    baseline_parameters: AnalyticalTuningParameters
    candidate_parameters: AnalyticalTuningParameters
    approved_parameters: AnalyticalTuningParameters
    baseline_evaluation: LearningEvaluation
    candidate_evaluation: LearningEvaluation
    paired_p_value: float
    status: LearningReleaseStatus
    partition_hashes: tuple[str, ...]
    trajectory_provenance_ids: tuple[str, ...]
    reversible: bool = True

    def __post_init__(self) -> None:
        if not self.release_id or not self.dataset_version:
            raise ValueError(
                "Offline learning release requires stable dataset identity."
            )
        if len(self.partition_hashes) != 3 or not self.trajectory_provenance_ids:
            raise ValueError(
                "Offline learning release requires locked data provenance."
            )
        if not 0 <= self.paired_p_value <= 1 or not self.reversible:
            raise ValueError(
                "Offline learning release must be reversible and testable."
            )
        grounding_regression = (
            self.baseline_evaluation.grounding_rate
            - self.candidate_evaluation.grounding_rate
        )
        safety_regression = (
            self.candidate_evaluation.critical_safety_rate
            < self.baseline_evaluation.critical_safety_rate
        )
        if self.status == LearningReleaseStatus.APPROVED:
            if (
                self.approved_parameters != self.candidate_parameters
                or self.candidate_evaluation.task_accuracy
                <= self.baseline_evaluation.task_accuracy
                or self.paired_p_value >= 0.05
                or grounding_regression > 0.005
                or safety_regression
            ):
                raise ValueError(
                    "Approved learning release failed a non-compensatory gate."
                )
        elif self.approved_parameters != self.baseline_parameters:
            raise ValueError("Rejected learning release must retain prior parameters.")


@dataclass(frozen=True, slots=True)
class DriftObservation:
    observation_id: str
    drift_type: DriftType
    expected_drift: bool
    severity: float
    unknown_hazard: bool
    unknown_language: bool
    unknown_provider_schema: bool
    source_latency_ratio: float
    image_domain_distance: float
    unsupported_claim_if_undetected: bool
    provenance_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.observation_id or not self.provenance_ids:
            raise ValueError("Drift observation requires identity and provenance.")
        if not 0 <= self.severity <= 1:
            raise ValueError("Drift severity must be bounded.")
        if self.source_latency_ratio < 0 or not 0 <= self.image_domain_distance <= 1:
            raise ValueError("Drift observation features must be bounded.")


@dataclass(frozen=True, slots=True)
class DriftAssessment:
    observation_id: str
    drift_type: DriftType
    detected: bool
    severe: bool
    signal_ids: tuple[str, ...]
    provenance_ids: tuple[str, ...]
    can_change_source_authority: bool = False
    can_change_safety_policy: bool = False

    def __post_init__(self) -> None:
        if not self.observation_id or not self.provenance_ids:
            raise ValueError("Drift assessment requires observation provenance.")
        if self.detected and not self.signal_ids:
            raise ValueError("Detected drift requires visible typed signals.")
        if self.can_change_source_authority or self.can_change_safety_policy:
            raise ValueError("Drift detection cannot change authority or policy.")


@dataclass(frozen=True, slots=True)
class DriftAdaptationRelease:
    release_id: str
    dataset_version: str
    status: DriftAdaptationStatus
    prior_parameters: AnalyticalTuningParameters
    candidate_parameters: AnalyticalTuningParameters
    approved_parameters: AnalyticalTuningParameters
    assessments: tuple[DriftAssessment, ...]
    drift_recall: float
    shifted_baseline_evaluation: LearningEvaluation
    shifted_candidate_evaluation: LearningEvaluation
    historical_baseline_evaluation: LearningEvaluation
    historical_candidate_evaluation: LearningEvaluation
    safe_mode_reason: str | None
    provenance_ids: tuple[str, ...]
    reversible: bool = True

    def __post_init__(self) -> None:
        if not self.release_id or not self.dataset_version or not self.provenance_ids:
            raise ValueError("Drift adaptation requires stable release provenance.")
        if not 0 <= self.drift_recall <= 1 or not self.reversible:
            raise ValueError("Drift adaptation must be bounded and reversible.")
        historical_degradation = (
            self.historical_baseline_evaluation.task_accuracy
            - self.historical_candidate_evaluation.task_accuracy
        )
        safety_regression = (
            self.historical_candidate_evaluation.critical_safety_rate
            < self.historical_baseline_evaluation.critical_safety_rate
        )
        if self.status == DriftAdaptationStatus.ADAPTED:
            if (
                self.approved_parameters != self.candidate_parameters
                or self.drift_recall < 0.90
                or self.shifted_candidate_evaluation.task_accuracy
                <= self.shifted_baseline_evaluation.task_accuracy
                or historical_degradation > 0.01
                or safety_regression
                or self.safe_mode_reason is not None
            ):
                raise ValueError("Approved drift adaptation failed its release gate.")
        elif (
            self.approved_parameters != self.prior_parameters
            or self.safe_mode_reason is None
        ):
            raise ValueError("Safe mode must retain prior approved parameters.")


@dataclass(frozen=True, slots=True)
class OptimizationProposal:
    proposal_id: str
    scope: OptimizationScope
    target_ids: tuple[str, ...]
    baseline_parameters: AnalyticalTuningParameters
    candidate_parameters: AnalyticalTuningParameters
    provenance_ids: tuple[str, ...]
    reversible: bool

    def __post_init__(self) -> None:
        if not self.proposal_id or not self.target_ids or not self.provenance_ids:
            raise ValueError("Optimization proposal requires identity and provenance.")
        if len(self.target_ids) != len(set(self.target_ids)):
            raise ValueError("Optimization proposal targets must be unique.")


@dataclass(frozen=True, slots=True)
class OptimizationFamilyEvaluation:
    family: str
    sample_count: int
    baseline_accuracy: float
    candidate_accuracy: float

    def __post_init__(self) -> None:
        if not self.family or self.sample_count < 1:
            raise ValueError("Optimization family requires identity and samples.")
        if any(
            not 0 <= value <= 1
            for value in (self.baseline_accuracy, self.candidate_accuracy)
        ):
            raise ValueError("Optimization family metrics must be bounded.")


@dataclass(frozen=True, slots=True)
class AutonomousOptimizationRelease:
    release_id: str
    dataset_version: str
    status: OptimizationStatus
    proposal: OptimizationProposal
    approved_parameters: AnalyticalTuningParameters
    family_evaluations: tuple[OptimizationFamilyEvaluation, ...]
    baseline_guardrail_evaluation: LearningEvaluation
    candidate_guardrail_evaluation: LearningEvaluation
    baseline_pass_eight: float
    candidate_pass_eight: float
    rejection_reason: str | None
    rollback_restored: bool
    provenance_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.release_id or not self.dataset_version or not self.provenance_ids:
            raise ValueError("Optimization release requires identity and provenance.")
        if any(
            not 0 <= value <= 1
            for value in (self.baseline_pass_eight, self.candidate_pass_eight)
        ):
            raise ValueError("Optimization repeated-run metrics must be bounded.")
        improved_families = sum(
            item.candidate_accuracy > item.baseline_accuracy
            for item in self.family_evaluations
        )
        safety_regression = (
            self.candidate_guardrail_evaluation.critical_safety_rate
            < self.baseline_guardrail_evaluation.critical_safety_rate
        )
        grounding_regression = (
            self.candidate_guardrail_evaluation.grounding_rate
            < self.baseline_guardrail_evaluation.grounding_rate
        )
        task_regression = (
            self.candidate_guardrail_evaluation.task_accuracy
            < self.baseline_guardrail_evaluation.task_accuracy
        )
        if self.status == OptimizationStatus.APPROVED:
            if (
                self.proposal.scope != OptimizationScope.ANALYTICAL_TUNING
                or not self.proposal.reversible
                or self.approved_parameters != self.proposal.candidate_parameters
                or improved_families < 3
                or self.candidate_pass_eight < self.baseline_pass_eight
                or safety_regression
                or grounding_regression
                or task_regression
                or self.rejection_reason is not None
                or self.rollback_restored
            ):
                raise ValueError(
                    "Approved autonomous optimization failed its release gate."
                )
        elif (
            self.approved_parameters != self.proposal.baseline_parameters
            or not self.rollback_restored
            or self.rejection_reason is None
        ):
            raise ValueError(
                "Rejected optimization must restore the prior approved state."
            )
