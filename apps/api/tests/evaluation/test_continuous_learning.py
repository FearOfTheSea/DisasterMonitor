import hashlib
import json
from dataclasses import replace
from pathlib import Path

import pytest
from test_coordination import _multimodal_state
from test_decision_support import FIXTURES as DECISION_FIXTURES
from test_decision_support import _products

from disaster_monitor.application.services.collaborative_investigation import (
    SAFETY_POLICY_FINGERPRINT,
)
from disaster_monitor.application.services.coordination_handoffs import (
    CoordinationHandoffPlanner,
)
from disaster_monitor.application.services.coordination_supervision import (
    CoordinationSupervisor,
    derive_analytical_focus_signals,
)
from disaster_monitor.application.services.drift_adaptation import (
    DistributionDriftDetector,
    DriftAdaptationController,
    load_drift_observations,
)
from disaster_monitor.application.services.governed_optimization import (
    GovernedAutonomousOptimizer,
)
from disaster_monitor.application.services.offline_learning import (
    APPROVED_GOVERNED_ANALYTICAL_TUNING_RELEASE_V3,
    BASELINE_ANALYTICAL_TUNING_V0,
    CURRENT_APPROVED_ANALYTICAL_TUNING_RELEASE,
    DRIFT_ADAPTED_ANALYTICAL_TUNING_V2,
    GOVERNED_ANALYTICAL_TUNING_V3,
    AnalyticalFollowupRanker,
    OfflineTrajectoryLearner,
    load_locked_trajectories,
)
from disaster_monitor.domain.learning import (
    AnalyticalFocus,
    AnalyticalTuningParameters,
    DriftAdaptationStatus,
    LearningPartition,
    LearningReleaseStatus,
    LearningTrajectory,
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
    dataset_version, benchmark, regression, production = _optimization_inputs()
    proposal = _optimization_proposal()
    release = GovernedAutonomousOptimizer().evaluate(
        dataset_version,
        proposal,
        benchmark_trajectories=benchmark,
        regression_trajectories=regression,
        production_trajectories=production,
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
    assert release.production_effect_count == 3
    assert release.production_regime_coverage == 1.0
    assert all(
        item.candidate_accuracy > item.baseline_accuracy
        for item in release.production_family_evaluations
    )
    approved_release = APPROVED_GOVERNED_ANALYTICAL_TUNING_RELEASE_V3
    fixture_path = FIXTURES / "optimization_benchmarks.v2.json"
    assert approved_release.optimizer_release_id == release.release_id
    assert approved_release.dataset_version == release.dataset_version
    assert approved_release.proposal_id == proposal.proposal_id
    assert approved_release.target_ids == proposal.target_ids
    assert approved_release.prior_parameters == proposal.baseline_parameters
    assert approved_release.released_parameters == release.approved_parameters
    assert approved_release.production_effect_count == release.production_effect_count
    assert (
        approved_release.evaluation_artifact_sha256
        == hashlib.sha256(fixture_path.read_bytes()).hexdigest()
    )


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
    dataset_version, benchmark, regression, production = _optimization_inputs()
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
        production_trajectories=production,
    )

    assert release.status == OptimizationStatus.REJECTED_PROTECTED_SCOPE
    assert release.approved_parameters == DRIFT_ADAPTED_ANALYTICAL_TUNING_V2
    assert release.rollback_restored
    assert release.rejection_reason == f"protected_scope:{scope.value}"


def test_cl_c_non_reversible_out_of_scope_and_safety_damage_restore_prior() -> None:
    dataset_version, benchmark, regression, production = _optimization_inputs()
    optimizer = GovernedAutonomousOptimizer()

    non_reversible = optimizer.evaluate(
        dataset_version,
        replace(_optimization_proposal(), reversible=False),
        benchmark_trajectories=benchmark,
        regression_trajectories=regression,
        production_trajectories=production,
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
        production_trajectories=production,
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
        production_trajectories=production,
    )
    assert rejected.status == OptimizationStatus.REJECTED_REGRESSION
    assert rejected.approved_parameters == DRIFT_ADAPTED_ANALYTICAL_TUNING_V2
    assert rejected.rollback_restored


def test_cl_c_runtime_supervisor_uses_exact_production_signals_and_release() -> None:
    production, episodes = _production_linkage_inputs()
    assert [
        (
            item.evidence_gap_signal,
            item.material_conflict_signal,
            item.multimodal_signal,
            item.routine_signal,
        )
        for item in production
    ] == [
        (0.2, 0.0, 0.0, 1.0),
        (0.2, 1 / 12, 0.0, 1.0),
        (0.2, 0.0, 1 / 9, 1.0),
    ]
    baseline_release = replace(
        CURRENT_APPROVED_ANALYTICAL_TUNING_RELEASE,
        release_id="analytical-tuning-release:v2-runtime-comparison",
        optimizer_release_id="autonomous-optimization:runtime-comparison-v2",
        prior_parameters=GOVERNED_ANALYTICAL_TUNING_V3,
        released_parameters=DRIFT_ADAPTED_ANALYTICAL_TUNING_V2,
    )
    baseline_supervisor = CoordinationSupervisor(
        focus_ranker=AnalyticalFollowupRanker(approved_release=baseline_release)
    )
    released_supervisor = CoordinationSupervisor()
    planner = CoordinationHandoffPlanner()

    for trajectory, (state, artifact, multimodal) in zip(
        production, episodes, strict=True
    ):
        handoffs = (
            planner.for_evidence_state(state),
            planner.for_decision_support(artifact),
            *((planner.for_multimodal_state(multimodal),) if multimodal else ()),
        )
        baseline = baseline_supervisor.run(
            state,
            handoffs,
            decision_support=artifact,
            multimodal_state=multimodal,
        )
        released = released_supervisor.run(
            state,
            handoffs,
            decision_support=artifact,
            multimodal_state=multimodal,
        )
        assert baseline.analytical_focus == AnalyticalFocus.ROUTINE_MONITORING
        assert released.analytical_focus == trajectory.gold_focus
        assert released.analytical_release_id == (
            CURRENT_APPROVED_ANALYTICAL_TUNING_RELEASE.release_id
        )
        assert released.analytical_parameter_set_id == (
            GOVERNED_ANALYTICAL_TUNING_V3.parameter_set_id
        )
        assert (
            released.status,
            released.sufficient,
            released.required_finding_keys,
            released.missing_finding_keys,
            released.termination_reason,
            released.safety_policy_fingerprint,
            released.evidence_ids,
            released.source_ids,
        ) == (
            baseline.status,
            baseline.sufficient,
            baseline.required_finding_keys,
            baseline.missing_finding_keys,
            baseline.termination_reason,
            baseline.safety_policy_fingerprint,
            baseline.evidence_ids,
            baseline.source_ids,
        )
        assert released.safety_policy_fingerprint == SAFETY_POLICY_FINGERPRINT


def test_cl_c_parameter_is_inert_outside_the_attenuated_regime() -> None:
    baseline = AnalyticalFollowupRanker(DRIFT_ADAPTED_ANALYTICAL_TUNING_V2)
    candidate = AnalyticalFollowupRanker(GOVERNED_ANALYTICAL_TUNING_V3)
    unchanged = _unchanged_production_inputs()
    assert [
        baseline.select(
            evidence_gap_signal=item.evidence_gap_signal,
            material_conflict_signal=item.material_conflict_signal,
            multimodal_signal=item.multimodal_signal,
            routine_signal=item.routine_signal,
        )
        for item in unchanged
    ] == [AnalyticalFocus.ROUTINE_MONITORING, AnalyticalFocus.MATERIAL_CONFLICTS]
    assert [
        candidate.select(
            evidence_gap_signal=item.evidence_gap_signal,
            material_conflict_signal=item.material_conflict_signal,
            multimodal_signal=item.multimodal_signal,
            routine_signal=item.routine_signal,
        )
        for item in unchanged
    ] == [AnalyticalFocus.ROUTINE_MONITORING, AnalyticalFocus.MATERIAL_CONFLICTS]


def test_cl_c_rejects_no_production_effect_and_unreachable_regimes() -> None:
    dataset_version, benchmark, regression, production = _optimization_inputs()
    optimizer = GovernedAutonomousOptimizer()
    no_effect = optimizer.evaluate(
        dataset_version,
        _optimization_proposal(),
        benchmark_trajectories=benchmark,
        regression_trajectories=regression,
        production_trajectories=_unchanged_production_inputs(),
    )
    assert no_effect.status == OptimizationStatus.REJECTED_UNREACHABLE
    assert no_effect.rejection_reason == "no_reachable_production_behavior_change"
    assert no_effect.approved_parameters == DRIFT_ADAPTED_ANALYTICAL_TUNING_V2
    assert no_effect.rollback_restored

    unreachable_benchmark = tuple(
        replace(item, evidence_gap_signal=0.19)
        if item.family == "attenuated_evidence_gap"
        else item
        for item in benchmark
    )
    unreachable = optimizer.evaluate(
        dataset_version,
        _optimization_proposal(),
        benchmark_trajectories=unreachable_benchmark,
        regression_trajectories=regression,
        production_trajectories=production,
    )
    assert unreachable.status == OptimizationStatus.REJECTED_UNREACHABLE
    assert unreachable.rejection_reason == "benchmark_uses_unreachable_signal_regime"
    assert unreachable.production_regime_coverage < 1.0
    assert unreachable.approved_parameters == DRIFT_ADAPTED_ANALYTICAL_TUNING_V2
    assert unreachable.rollback_restored


def test_cl_c_synthetic_gain_cannot_compensate_for_production_regression() -> None:
    dataset_version, benchmark, regression, production = _optimization_inputs()
    fault_injected_adjudications = tuple(
        replace(item, gold_focus=AnalyticalFocus.ROUTINE_MONITORING)
        for item in production
    )
    release = GovernedAutonomousOptimizer().evaluate(
        dataset_version,
        _optimization_proposal(),
        benchmark_trajectories=benchmark,
        regression_trajectories=regression,
        production_trajectories=fault_injected_adjudications,
    )
    assert all(
        item.candidate_accuracy > item.baseline_accuracy
        for item in release.family_evaluations
    )
    assert (
        release.production_candidate_evaluation.task_accuracy
        < release.production_baseline_evaluation.task_accuracy
    )
    assert release.status == OptimizationStatus.REJECTED_REGRESSION
    assert release.approved_parameters == DRIFT_ADAPTED_ANALYTICAL_TUNING_V2
    assert release.rollback_restored


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
        (FIXTURES / "optimization_benchmarks.v2.json").read_text(encoding="utf-8")
    )
    assert payload["fixture_version"] == "dm-cl-c-v2"
    dataset_version, benchmark = load_locked_trajectories(payload)
    _, _, historical, shifted = _drift_inputs()
    production, _episodes = _production_linkage_inputs()
    return dataset_version, benchmark, (*historical, *shifted), production


def _production_linkage_inputs():
    fixture = json.loads(
        (DECISION_FIXTURES / "scenario_cases.v1.json").read_text(encoding="utf-8")
    )
    scenarios = {str(item["id"]): item for item in fixture["cases"]}
    gap_state, *_gap_products, gap_artifact = _products(scenarios["positive-injuries"])
    conflict_state, *_conflict_products, conflict_artifact = _products(
        scenarios["conflict-neutral"]
    )
    multimodal_state, *_multimodal_products, multimodal_artifact = _products(
        scenarios["positive-injuries"]
    )
    multimodal = _multimodal_state(multimodal_state, "cl-c-production-multimodal")
    episodes = (
        (gap_state, gap_artifact, None),
        (conflict_state, conflict_artifact, None),
        (multimodal_state, multimodal_artifact, multimodal),
    )
    identities = (
        (
            "cl-c-production-gap",
            "attenuated_evidence_gap",
            AnalyticalFocus.EVIDENCE_GAPS,
        ),
        (
            "cl-c-production-conflict",
            "attenuated_material_conflict",
            AnalyticalFocus.MATERIAL_CONFLICTS,
        ),
        (
            "cl-c-production-multimodal",
            "attenuated_multimodal_review",
            AnalyticalFocus.MULTIMODAL_REVIEW,
        ),
    )
    trajectories = tuple(
        _production_trajectory(
            case_id,
            family,
            gold_focus,
            state,
            artifact,
            multimodal_evidence,
        )
        for (case_id, family, gold_focus), (
            state,
            artifact,
            multimodal_evidence,
        ) in zip(identities, episodes, strict=True)
    )
    return trajectories, episodes


def _unchanged_production_inputs() -> tuple[LearningTrajectory, ...]:
    all_claims = ("fatalities", "injuries", "missing", "evacuations")
    routine_case = {
        "id": "cl-c-production-routine",
        "hazard": "earthquake",
        "country_code": "JPN",
        "magnitude": 4.2,
        "reports": [
            {
                "source_id": "cl-c-routine-source",
                "hours_ago": 1,
                "facts": [
                    *(
                        {"category": category, "value": "0", "status": "confirmed"}
                        for category in all_claims
                    ),
                    {
                        "category": "physical_damage",
                        "value": "No observed damage",
                        "status": "confirmed",
                    },
                    {
                        "category": "infrastructure",
                        "value": "No operational disruption",
                        "status": "confirmed",
                    },
                ],
            }
        ],
    }
    conflict_case = {
        "id": "cl-c-production-strong-conflict",
        "hazard": "earthquake",
        "country_code": "JPN",
        "magnitude": 4.2,
        "reports": [
            {
                "source_id": "cl-c-conflict-positive",
                "hours_ago": 2,
                "facts": [
                    {"category": category, "value": "2", "status": "confirmed"}
                    for category in all_claims
                ],
            },
            {
                "source_id": "cl-c-conflict-zero",
                "hours_ago": 1,
                "facts": [
                    {"category": category, "value": "0", "status": "confirmed"}
                    for category in all_claims
                ],
            },
        ],
    }
    routine_state, *_routine_products, routine_artifact = _products(routine_case)
    conflict_state, *_conflict_products, conflict_artifact = _products(conflict_case)
    return (
        _production_trajectory(
            "cl-c-production-routine",
            "routine_unchanged",
            AnalyticalFocus.ROUTINE_MONITORING,
            routine_state,
            routine_artifact,
            None,
        ),
        _production_trajectory(
            "cl-c-production-strong-conflict",
            "strong_conflict_unchanged",
            AnalyticalFocus.MATERIAL_CONFLICTS,
            conflict_state,
            conflict_artifact,
            None,
        ),
    )


def _production_trajectory(
    case_id,
    family,
    gold_focus,
    state,
    artifact,
    multimodal,
) -> LearningTrajectory:
    signals = derive_analytical_focus_signals(state, artifact, multimodal)
    provenance = [state.state_version, artifact.artifact_id]
    if multimodal is not None:
        provenance.append(multimodal.state_version)
    return LearningTrajectory(
        trajectory_id=case_id,
        family=family,
        partition=LearningPartition.TEST,
        evidence_gap_signal=signals["evidence_gap_signal"],
        material_conflict_signal=signals["material_conflict_signal"],
        multimodal_signal=signals["multimodal_signal"],
        routine_signal=signals["routine_signal"],
        gold_focus=gold_focus,
        grounded=True,
        critical_safety_pass=True,
        unsafe_focuses=(),
        ungrounded_focuses=(),
        provenance_ids=tuple(provenance),
    )


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
