import json
from dataclasses import replace
from pathlib import Path

import pytest

from disaster_monitor.application.services.offline_learning import (
    BASELINE_ANALYTICAL_TUNING_V0,
    OfflineTrajectoryLearner,
    load_locked_trajectories,
)
from disaster_monitor.domain.learning import (
    AnalyticalTuningParameters,
    LearningPartition,
    LearningReleaseStatus,
)

FIXTURES = Path(__file__).parent / "fixtures" / "continuous_learning"


def _load() -> tuple[str, tuple]:
    payload = json.loads(
        (FIXTURES / "offline_trajectories.v1.json").read_text(encoding="utf-8")
    )
    assert payload["fixture_version"] == "dm-cl-a-v1"
    return load_locked_trajectories(payload)


def test_cl_a_release_gate() -> None:
    dataset_version, trajectories = _load()
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
    dataset_version, trajectories = _load()
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
    dataset_version, trajectories = _load()
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
