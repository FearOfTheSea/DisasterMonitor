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


@dataclass(frozen=True, slots=True)
class AnalyticalTuningParameters:
    parameter_set_id: str
    evidence_gap_weight: float
    material_conflict_weight: float
    multimodal_review_weight: float
    routine_monitoring_weight: float
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
