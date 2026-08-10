"""Locked-partition offline tuning for non-authority analytical focus only."""

from collections.abc import Mapping
from hashlib import sha256
from math import comb

from disaster_monitor.domain.learning import (
    AnalyticalFocus,
    AnalyticalTuningParameters,
    LearningEvaluation,
    LearningPartition,
    LearningReleaseStatus,
    LearningTrajectory,
    OfflineLearningRelease,
)

BASELINE_ANALYTICAL_TUNING_V0 = AnalyticalTuningParameters(
    parameter_set_id="analytical-tuning:v0",
    evidence_gap_weight=1.0,
    material_conflict_weight=1.0,
    multimodal_review_weight=1.0,
    routine_monitoring_weight=1.0,
)
APPROVED_ANALYTICAL_TUNING_V1 = AnalyticalTuningParameters(
    parameter_set_id="analytical-tuning:v1",
    evidence_gap_weight=2.0,
    material_conflict_weight=4.0,
    multimodal_review_weight=3.0,
    routine_monitoring_weight=1.0,
)
_CANDIDATES = (
    APPROVED_ANALYTICAL_TUNING_V1,
    AnalyticalTuningParameters(
        parameter_set_id="analytical-tuning:gap-heavy",
        evidence_gap_weight=4.0,
        material_conflict_weight=2.0,
        multimodal_review_weight=1.0,
        routine_monitoring_weight=1.0,
    ),
    AnalyticalTuningParameters(
        parameter_set_id="analytical-tuning:multimodal-heavy",
        evidence_gap_weight=1.0,
        material_conflict_weight=2.0,
        multimodal_review_weight=5.0,
        routine_monitoring_weight=1.0,
    ),
)


class AnalyticalFollowupRanker:
    """Rank an inspectable analytical focus without affecting authority or safety."""

    def __init__(
        self, parameters: AnalyticalTuningParameters = APPROVED_ANALYTICAL_TUNING_V1
    ) -> None:
        self.parameters = parameters

    def select(
        self,
        *,
        evidence_gap_signal: float,
        material_conflict_signal: float,
        multimodal_signal: float,
        routine_signal: float,
    ) -> AnalyticalFocus:
        scores = {
            AnalyticalFocus.EVIDENCE_GAPS: (
                evidence_gap_signal * self.parameters.evidence_gap_weight
            ),
            AnalyticalFocus.MATERIAL_CONFLICTS: (
                material_conflict_signal * self.parameters.material_conflict_weight
            ),
            AnalyticalFocus.MULTIMODAL_REVIEW: (
                multimodal_signal * self.parameters.multimodal_review_weight
            ),
            AnalyticalFocus.ROUTINE_MONITORING: (
                routine_signal * self.parameters.routine_monitoring_weight
            ),
        }
        return max(scores, key=scores.__getitem__)


class OfflineTrajectoryLearner:
    """Select on train/dev and release only after a locked test safety barrier."""

    def evaluate(
        self,
        dataset_version: str,
        trajectories: tuple[LearningTrajectory, ...],
    ) -> OfflineLearningRelease:
        _validate_partitions(trajectories)
        train = _partition(trajectories, LearningPartition.TRAIN)
        dev = _partition(trajectories, LearningPartition.DEV)
        test = _partition(trajectories, LearningPartition.TEST)
        train_best = max(
            _CANDIDATES,
            key=lambda item: (
                _evaluate(item, train).task_accuracy,
                item.parameter_set_id,
            ),
        )
        selected = max(
            (train_best, *_CANDIDATES),
            key=lambda item: (
                _evaluate(item, dev).task_accuracy,
                _evaluate(item, train).task_accuracy,
                item.parameter_set_id,
            ),
        )
        baseline_evaluation = _evaluate(BASELINE_ANALYTICAL_TUNING_V0, test)
        candidate_evaluation = _evaluate(selected, test)
        paired_p_value = _paired_sign_test(
            BASELINE_ANALYTICAL_TUNING_V0, selected, test
        )
        grounding_regression = (
            baseline_evaluation.grounding_rate - candidate_evaluation.grounding_rate
        )
        if (
            candidate_evaluation.critical_safety_rate
            < baseline_evaluation.critical_safety_rate
        ):
            status = LearningReleaseStatus.REJECTED_SAFETY
        elif grounding_regression > 0.005:
            status = LearningReleaseStatus.REJECTED_GROUNDING
        elif (
            candidate_evaluation.task_accuracy <= baseline_evaluation.task_accuracy
            or paired_p_value >= 0.05
        ):
            status = LearningReleaseStatus.REJECTED_NO_SIGNIFICANT_IMPROVEMENT
        else:
            status = LearningReleaseStatus.APPROVED
        approved = (
            selected
            if status == LearningReleaseStatus.APPROVED
            else BASELINE_ANALYTICAL_TUNING_V0
        )
        partition_hashes = tuple(
            _partition_hash(_partition(trajectories, partition))
            for partition in LearningPartition
        )
        provenance_ids = tuple(
            dict.fromkeys(
                provenance_id
                for trajectory in trajectories
                for provenance_id in trajectory.provenance_ids
            )
        )
        material = "|".join(
            (
                dataset_version,
                selected.parameter_set_id,
                status.value,
                *partition_hashes,
            )
        )
        return OfflineLearningRelease(
            release_id=(
                f"offline-learning:{sha256(material.encode('utf-8')).hexdigest()[:24]}"
            ),
            dataset_version=dataset_version,
            baseline_parameters=BASELINE_ANALYTICAL_TUNING_V0,
            candidate_parameters=selected,
            approved_parameters=approved,
            baseline_evaluation=baseline_evaluation,
            candidate_evaluation=candidate_evaluation,
            paired_p_value=paired_p_value,
            status=status,
            partition_hashes=partition_hashes,
            trajectory_provenance_ids=provenance_ids,
        )


def load_locked_trajectories(
    payload: Mapping[str, object],
) -> tuple[str, tuple[LearningTrajectory, ...]]:
    if set(payload) != {"fixture_version", "dataset_version", "groups"}:
        raise ValueError("Learning fixture schema is invalid.")
    dataset_version = _string(payload["dataset_version"], "dataset_version")
    groups = payload["groups"]
    if not isinstance(groups, list) or not groups:
        raise ValueError("Learning fixture requires trajectory groups.")
    trajectories: list[LearningTrajectory] = []
    for group in groups:
        if not isinstance(group, Mapping):
            raise ValueError("Learning trajectory group must be an object.")
        expected = {
            "id_prefix",
            "family",
            "partition",
            "count",
            "signals",
            "gold_focus",
            "grounded",
            "critical_safety_pass",
            "unsafe_focuses",
            "ungrounded_focuses",
            "provenance_prefix",
        }
        if set(group) != expected:
            raise ValueError("Learning trajectory group schema is invalid.")
        count = group["count"]
        signals = group["signals"]
        if not isinstance(count, int) or not 1 <= count <= 1_000:
            raise ValueError("Learning trajectory group count is invalid.")
        if not isinstance(signals, Mapping) or set(signals) != {
            "evidence_gap",
            "material_conflict",
            "multimodal",
            "routine",
        }:
            raise ValueError("Learning trajectory signals are invalid.")
        unsafe = _focus_list(group["unsafe_focuses"])
        ungrounded = _focus_list(group["ungrounded_focuses"])
        for index in range(count):
            trajectories.append(
                LearningTrajectory(
                    trajectory_id=(
                        f"{_string(group['id_prefix'], 'id_prefix')}:{index:03d}"
                    ),
                    family=_string(group["family"], "family"),
                    partition=LearningPartition(
                        _string(group["partition"], "partition")
                    ),
                    evidence_gap_signal=float(signals["evidence_gap"]),
                    material_conflict_signal=float(signals["material_conflict"]),
                    multimodal_signal=float(signals["multimodal"]),
                    routine_signal=float(signals["routine"]),
                    gold_focus=AnalyticalFocus(
                        _string(group["gold_focus"], "gold_focus")
                    ),
                    grounded=group["grounded"] is True,
                    critical_safety_pass=group["critical_safety_pass"] is True,
                    unsafe_focuses=unsafe,
                    ungrounded_focuses=ungrounded,
                    provenance_ids=(
                        f"{_string(group['provenance_prefix'], 'provenance_prefix')}"
                        f":{index:03d}",
                    ),
                )
            )
    return dataset_version, tuple(trajectories)


def _evaluate(
    parameters: AnalyticalTuningParameters,
    trajectories: tuple[LearningTrajectory, ...],
) -> LearningEvaluation:
    ranker = AnalyticalFollowupRanker(parameters)
    predictions = tuple(_prediction(ranker, item) for item in trajectories)
    return LearningEvaluation(
        task_accuracy=sum(
            prediction == trajectory.gold_focus
            for prediction, trajectory in zip(predictions, trajectories, strict=True)
        )
        / len(trajectories),
        grounding_rate=sum(
            trajectory.grounded and prediction not in trajectory.ungrounded_focuses
            for prediction, trajectory in zip(predictions, trajectories, strict=True)
        )
        / len(trajectories),
        critical_safety_rate=sum(
            trajectory.critical_safety_pass
            and prediction not in trajectory.unsafe_focuses
            for prediction, trajectory in zip(predictions, trajectories, strict=True)
        )
        / len(trajectories),
    )


def _prediction(
    ranker: AnalyticalFollowupRanker, trajectory: LearningTrajectory
) -> AnalyticalFocus:
    return ranker.select(
        evidence_gap_signal=trajectory.evidence_gap_signal,
        material_conflict_signal=trajectory.material_conflict_signal,
        multimodal_signal=trajectory.multimodal_signal,
        routine_signal=trajectory.routine_signal,
    )


def _paired_sign_test(
    baseline: AnalyticalTuningParameters,
    candidate: AnalyticalTuningParameters,
    trajectories: tuple[LearningTrajectory, ...],
) -> float:
    baseline_ranker = AnalyticalFollowupRanker(baseline)
    candidate_ranker = AnalyticalFollowupRanker(candidate)
    candidate_only = 0
    baseline_only = 0
    for trajectory in trajectories:
        baseline_correct = (
            _prediction(baseline_ranker, trajectory) == trajectory.gold_focus
        )
        candidate_correct = (
            _prediction(candidate_ranker, trajectory) == trajectory.gold_focus
        )
        candidate_only += candidate_correct and not baseline_correct
        baseline_only += baseline_correct and not candidate_correct
    discordant = candidate_only + baseline_only
    if discordant == 0:
        return 1.0
    tail = min(candidate_only, baseline_only)
    probability = float(
        sum(comb(discordant, index) for index in range(tail + 1))
    ) / float(2**discordant)
    return float(min(1.0, 2 * probability))


def _partition(
    trajectories: tuple[LearningTrajectory, ...], partition: LearningPartition
) -> tuple[LearningTrajectory, ...]:
    selected = tuple(item for item in trajectories if item.partition == partition)
    if not selected:
        raise ValueError(f"Learning partition {partition.value} is empty.")
    return selected


def _validate_partitions(trajectories: tuple[LearningTrajectory, ...]) -> None:
    ids = [item.trajectory_id for item in trajectories]
    provenance = [value for item in trajectories for value in item.provenance_ids]
    if len(ids) != len(set(ids)) or len(provenance) != len(set(provenance)):
        raise ValueError("Learning train/dev/test identities or provenance overlap.")


def _partition_hash(trajectories: tuple[LearningTrajectory, ...]) -> str:
    material = "|".join(
        sorted(
            f"{item.trajectory_id}:{','.join(item.provenance_ids)}"
            for item in trajectories
        )
    )
    return sha256(material.encode("utf-8")).hexdigest()


def _focus_list(value: object) -> tuple[AnalyticalFocus, ...]:
    if not isinstance(value, list):
        raise ValueError("Learning focus constraints must be lists.")
    return tuple(AnalyticalFocus(_string(item, "focus")) for item in value)


def _string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 200:
        raise ValueError(f"Learning {field} must be a bounded string.")
    return value.strip()
