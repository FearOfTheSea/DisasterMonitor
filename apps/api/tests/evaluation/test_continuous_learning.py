from dataclasses import replace

import pytest
from continuous_learning_fixtures import drift_inputs, load_trajectories

from disaster_monitor.application.services.drift_adaptation import (
    DistributionDriftDetector,
    DriftAdaptationController,
)
from disaster_monitor.application.services.offline_learning import (
    BASELINE_ANALYTICAL_TUNING_V0,
    OfflineTrajectoryLearner,
)
from disaster_monitor.domain.learning import (
    AnalyticalTuningParameters,
    DriftAdaptationStatus,
    LearningPartition,
    LearningReleaseStatus,
)


def test_cl_a_release_gate() -> None:
    dataset_version, trajectories = load_trajectories()
    release = OfflineTrajectoryLearner().evaluate(dataset_version, trajectories)
    assert release.status == LearningReleaseStatus.APPROVED
    assert release.approved_parameters == release.candidate_parameters
    assert (
        release.candidate_evaluation.task_accuracy
        > release.baseline_evaluation.task_accuracy
    )
    assert release.paired_p_value < 0.05
    assert (
        release.candidate_evaluation.critical_safety_rate
        >= release.baseline_evaluation.critical_safety_rate
    )
    grounding_regression = (
        release.baseline_evaluation.grounding_rate
        - release.candidate_evaluation.grounding_rate
    )
    assert grounding_regression <= 0.005
    assert len(release.partition_hashes) == 3
    assert len(set(release.partition_hashes)) == 3
    assert release.trajectory_provenance_ids
    partition_ids = {
        partition: {
            item.trajectory_id for item in trajectories if item.partition == partition
        }
        for partition in LearningPartition
    }
    assert (
        not partition_ids[LearningPartition.TRAIN]
        & partition_ids[LearningPartition.DEV]
    )
    assert (
        not partition_ids[LearningPartition.TRAIN]
        & partition_ids[LearningPartition.TEST]
    )
    assert (
        not partition_ids[LearningPartition.DEV] & partition_ids[LearningPartition.TEST]
    )


def test_cl_a_non_compensatory_regressions_keep_prior_parameters() -> None:
    dataset_version, trajectories = load_trajectories()
    safety_regression = tuple(
        replace(item, unsafe_focuses=(item.gold_focus,))
        if item.partition == LearningPartition.TEST
        and item.family in {"conflict_resolution", "multimodal_review"}
        else item
        for item in trajectories
    )
    safety_release = OfflineTrajectoryLearner().evaluate(
        dataset_version, safety_regression
    )
    assert safety_release.status == LearningReleaseStatus.REJECTED_SAFETY
    assert safety_release.approved_parameters == BASELINE_ANALYTICAL_TUNING_V0

    grounding_regression = tuple(
        replace(item, ungrounded_focuses=(item.gold_focus,))
        if item.partition == LearningPartition.TEST
        and item.family in {"conflict_resolution", "multimodal_review"}
        else item
        for item in trajectories
    )
    grounding_release = OfflineTrajectoryLearner().evaluate(
        dataset_version, grounding_regression
    )
    assert grounding_release.status == LearningReleaseStatus.REJECTED_GROUNDING
    assert grounding_release.approved_parameters == BASELINE_ANALYTICAL_TUNING_V0


def test_cl_a_rejects_partition_overlap_and_authority_bearing_parameters() -> None:
    dataset_version, trajectories = load_trajectories()
    train = next(
        item for item in trajectories if item.partition == LearningPartition.TRAIN
    )
    dev_index = next(
        index
        for index, item in enumerate(trajectories)
        if item.partition == LearningPartition.DEV
    )
    overlapped = (
        *trajectories[:dev_index],
        replace(trajectories[dev_index], trajectory_id=train.trajectory_id),
        *trajectories[dev_index + 1 :],
    )
    with pytest.raises(ValueError, match="overlap"):
        OfflineTrajectoryLearner().evaluate(dataset_version, overlapped)

    with pytest.raises(ValueError, match="authority or safety"):
        AnalyticalTuningParameters(
            parameter_set_id="unsafe",
            evidence_gap_weight=1,
            material_conflict_weight=1,
            multimodal_review_weight=1,
            routine_monitoring_weight=1,
            source_authority_mutable=True,
        )


def test_cl_b_release_gate() -> None:
    dataset_version, observations, historical, shifted = drift_inputs()
    release = DriftAdaptationController().evaluate(
        dataset_version,
        observations,
        historical_trajectories=historical,
        shifted_trajectories=shifted,
    )
    assert release.status == DriftAdaptationStatus.ADAPTED
    assert release.drift_recall >= 0.90
    assert (
        release.shifted_candidate_evaluation.task_accuracy
        > release.shifted_baseline_evaluation.task_accuracy
    )
    historical_degradation = (
        release.historical_baseline_evaluation.task_accuracy
        - release.historical_candidate_evaluation.task_accuracy
    )
    assert historical_degradation <= 0.01
    assert (
        release.historical_candidate_evaluation.critical_safety_rate
        >= release.historical_baseline_evaluation.critical_safety_rate
    )
    assert release.approved_parameters.parameter_set_id == (
        "analytical-tuning:v2-drift-adapted"
    )
    assert all(
        not item.can_change_source_authority and not item.can_change_safety_policy
        for item in release.assessments
    )


def test_cl_b_severe_missed_shift_and_baseline_damage_enter_safe_mode() -> None:
    dataset_version, observations, historical, shifted = drift_inputs()
    lax_detector = DistributionDriftDetector(
        latency_ratio_threshold=10,
        image_distance_threshold=1,
    )
    missed = DriftAdaptationController(lax_detector).evaluate(
        dataset_version,
        observations,
        historical_trajectories=historical,
        shifted_trajectories=shifted,
    )
    assert missed.status == DriftAdaptationStatus.NON_ADAPTIVE_SAFE_MODE
    assert missed.safe_mode_reason == "severe_undetected_shift"
    assert missed.approved_parameters == missed.prior_parameters

    safety_damaged = tuple(
        replace(
            item,
            material_conflict_signal=0.45,
            unsafe_focuses=(item.gold_focus,),
        )
        if item.family == "conflict_resolution"
        else item
        for item in historical
    )
    damaged = DriftAdaptationController().evaluate(
        dataset_version,
        observations,
        historical_trajectories=safety_damaged,
        shifted_trajectories=shifted,
    )
    assert damaged.status == DriftAdaptationStatus.NON_ADAPTIVE_SAFE_MODE
    assert damaged.safe_mode_reason == "critical_safety_regression"
    assert damaged.approved_parameters == damaged.prior_parameters
