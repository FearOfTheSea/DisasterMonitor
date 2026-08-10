import json
from dataclasses import replace
from pathlib import Path

import pytest

from disaster_monitor.application.services.drift_adaptation import (
    DistributionDriftDetector,
    DriftAdaptationController,
    load_drift_observations,
)
from disaster_monitor.application.services.governed_optimization import (
    GovernedAutonomousOptimizer,
)
from disaster_monitor.application.services.offline_learning import (
    BASELINE_ANALYTICAL_TUNING_V0,
    DRIFT_ADAPTED_ANALYTICAL_TUNING_V2,
    GOVERNED_ANALYTICAL_TUNING_V3,
    OfflineTrajectoryLearner,
    load_locked_trajectories,
)
from disaster_monitor.domain.learning import (
    AnalyticalFocus,
    AnalyticalTuningParameters,
    DriftAdaptationStatus,
    LearningPartition,
    LearningReleaseStatus,
    OptimizationProposal,
    OptimizationScope,
    OptimizationStatus,
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


def test_cl_b_release_gate() -> None:
    dataset_version, observations, historical, shifted = _drift_inputs()
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
    dataset_version, observations, historical, shifted = _drift_inputs()
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


def test_cl_c_governed_multi_benchmark_release_gate() -> None:
    dataset_version, benchmark, regression = _optimization_inputs()
    proposal = _optimization_proposal()
    release = GovernedAutonomousOptimizer().evaluate(
        dataset_version,
        proposal,
        benchmark_trajectories=benchmark,
        regression_trajectories=regression,
    )

    assert release.status == OptimizationStatus.APPROVED
    assert release.approved_parameters == GOVERNED_ANALYTICAL_TUNING_V3
    assert len(release.family_evaluations) == 3
    assert all(
        item.candidate_accuracy > item.baseline_accuracy
        for item in release.family_evaluations
    )
    assert release.candidate_pass_eight >= release.baseline_pass_eight
    assert (
        release.candidate_guardrail_evaluation.critical_safety_rate
        >= release.baseline_guardrail_evaluation.critical_safety_rate
    )
    assert (
        release.candidate_guardrail_evaluation.grounding_rate
        >= release.baseline_guardrail_evaluation.grounding_rate
    )
    assert proposal.target_ids == ("analytical_tuning.attenuated_signal_boost",)
    assert proposal.reversible
    assert not release.rollback_restored


@pytest.mark.parametrize(
    "scope,target",
    (
        (OptimizationScope.TRUST_REGISTRY, "trusted_source_catalog"),
        (OptimizationScope.PERMISSIONS, "specialist_permissions"),
        (OptimizationScope.SAFETY_THRESHOLDS, "critical_safety_thresholds"),
        (
            OptimizationScope.HIGH_CONSEQUENCE_AUTHORITY,
            "public_warning_authority",
        ),
    ),
)
def test_cl_c_protected_self_changes_are_rejected_and_rolled_back(
    scope: OptimizationScope, target: str
) -> None:
    dataset_version, benchmark, regression = _optimization_inputs()
    proposal = replace(
        _optimization_proposal(),
        proposal_id=f"cl-c-protected:{scope.value}",
        scope=scope,
        target_ids=(target,),
    )
    release = GovernedAutonomousOptimizer().evaluate(
        dataset_version,
        proposal,
        benchmark_trajectories=benchmark,
        regression_trajectories=regression,
    )

    assert release.status == OptimizationStatus.REJECTED_PROTECTED_SCOPE
    assert release.approved_parameters == DRIFT_ADAPTED_ANALYTICAL_TUNING_V2
    assert release.rollback_restored
    assert release.rejection_reason == f"protected_scope:{scope.value}"


def test_cl_c_non_reversible_out_of_scope_and_safety_damage_restore_prior() -> None:
    dataset_version, benchmark, regression = _optimization_inputs()
    optimizer = GovernedAutonomousOptimizer()

    non_reversible = optimizer.evaluate(
        dataset_version,
        replace(_optimization_proposal(), reversible=False),
        benchmark_trajectories=benchmark,
        regression_trajectories=regression,
    )
    assert non_reversible.status == OptimizationStatus.REJECTED_NOT_REVERSIBLE
    assert non_reversible.rollback_restored

    weight_change = replace(
        GOVERNED_ANALYTICAL_TUNING_V3,
        parameter_set_id="analytical-tuning:disallowed-weight-change",
        evidence_gap_weight=3,
    )
    outside_allowlist = optimizer.evaluate(
        dataset_version,
        replace(_optimization_proposal(), candidate_parameters=weight_change),
        benchmark_trajectories=benchmark,
        regression_trajectories=regression,
    )
    assert outside_allowlist.status == OptimizationStatus.REJECTED_OUTSIDE_ALLOWLIST
    assert outside_allowlist.rollback_restored

    first, *remaining = regression
    safety_damaged = (
        replace(
            first,
            evidence_gap_signal=0.2,
            material_conflict_signal=0,
            multimodal_signal=0,
            routine_signal=1,
            gold_focus=AnalyticalFocus.EVIDENCE_GAPS,
            unsafe_focuses=(AnalyticalFocus.EVIDENCE_GAPS,),
        ),
        *remaining,
    )
    rejected = optimizer.evaluate(
        dataset_version,
        _optimization_proposal(),
        benchmark_trajectories=benchmark,
        regression_trajectories=safety_damaged,
    )
    assert rejected.status == OptimizationStatus.REJECTED_REGRESSION
    assert rejected.approved_parameters == DRIFT_ADAPTED_ANALYTICAL_TUNING_V2
    assert rejected.rollback_restored


def _drift_inputs():
    observation_payload = json.loads(
        (FIXTURES / "drift_observations.v1.json").read_text(encoding="utf-8")
    )
    assert observation_payload["fixture_version"] == "dm-cl-b-v1"
    dataset_version, observations = load_drift_observations(observation_payload)
    _, all_historical = _load()
    historical = tuple(
        item for item in all_historical if item.partition == LearningPartition.TEST
    )
    shifted_payload = json.loads(
        (FIXTURES / "shifted_trajectories.v1.json").read_text(encoding="utf-8")
    )
    assert shifted_payload["fixture_version"] == "dm-cl-b-shift-v1"
    _, shifted = load_locked_trajectories(shifted_payload)
    return dataset_version, observations, historical, shifted


def _optimization_inputs():
    payload = json.loads(
        (FIXTURES / "optimization_benchmarks.v1.json").read_text(encoding="utf-8")
    )
    assert payload["fixture_version"] == "dm-cl-c-v1"
    dataset_version, benchmark = load_locked_trajectories(payload)
    _, _, historical, shifted = _drift_inputs()
    return dataset_version, benchmark, (*historical, *shifted)


def _optimization_proposal() -> OptimizationProposal:
    return OptimizationProposal(
        proposal_id="cl-c:attenuated-signal-boost:v3",
        scope=OptimizationScope.ANALYTICAL_TUNING,
        target_ids=("analytical_tuning.attenuated_signal_boost",),
        baseline_parameters=DRIFT_ADAPTED_ANALYTICAL_TUNING_V2,
        candidate_parameters=GOVERNED_ANALYTICAL_TUNING_V3,
        provenance_ids=("cl-c:optimizer-proposal:v3",),
        reversible=True,
    )
