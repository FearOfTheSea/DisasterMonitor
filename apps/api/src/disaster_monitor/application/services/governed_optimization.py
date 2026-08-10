"""Governed autonomous optimization for one reversible analytical parameter."""

from collections import defaultdict
from hashlib import sha256

from disaster_monitor.application.services.offline_learning import (
    AnalyticalFollowupRanker,
    evaluate_parameters,
)
from disaster_monitor.domain.learning import (
    AnalyticalTuningParameters,
    AutonomousOptimizationRelease,
    LearningTrajectory,
    OptimizationFamilyEvaluation,
    OptimizationProposal,
    OptimizationScope,
    OptimizationStatus,
)

_ALLOWED_TARGETS = ("analytical_tuning.attenuated_signal_boost",)


class GovernedAutonomousOptimizer:
    """Evaluate a proposal and atomically retain or restore approved tuning."""

    def evaluate(
        self,
        dataset_version: str,
        proposal: OptimizationProposal,
        *,
        benchmark_trajectories: tuple[LearningTrajectory, ...],
        regression_trajectories: tuple[LearningTrajectory, ...],
    ) -> AutonomousOptimizationRelease:
        if not dataset_version or not benchmark_trajectories:
            raise ValueError("Optimization requires a versioned multi-benchmark set.")
        if not regression_trajectories:
            raise ValueError("Optimization requires an adversarial regression set.")

        families: dict[str, list[LearningTrajectory]] = defaultdict(list)
        for trajectory in benchmark_trajectories:
            families[trajectory.family].append(trajectory)
        family_evaluations = tuple(
            OptimizationFamilyEvaluation(
                family=family,
                sample_count=len(items),
                baseline_accuracy=evaluate_parameters(
                    proposal.baseline_parameters, tuple(items)
                ).task_accuracy,
                candidate_accuracy=evaluate_parameters(
                    proposal.candidate_parameters, tuple(items)
                ).task_accuracy,
            )
            for family, items in sorted(families.items())
        )
        guardrail_trajectories = (*benchmark_trajectories, *regression_trajectories)
        baseline_guardrails = evaluate_parameters(
            proposal.baseline_parameters, guardrail_trajectories
        )
        candidate_guardrails = evaluate_parameters(
            proposal.candidate_parameters, guardrail_trajectories
        )
        baseline_pass_eight = _pass_eight(
            proposal.baseline_parameters, guardrail_trajectories
        )
        candidate_pass_eight = _pass_eight(
            proposal.candidate_parameters, guardrail_trajectories
        )
        improved_families = sum(
            item.candidate_accuracy > item.baseline_accuracy
            for item in family_evaluations
        )

        protected_scope = proposal.scope != OptimizationScope.ANALYTICAL_TUNING
        allowlisted = (
            proposal.target_ids == _ALLOWED_TARGETS
            and _changes_only_attenuated_signal_boost(proposal)
        )
        if protected_scope:
            status = OptimizationStatus.REJECTED_PROTECTED_SCOPE
            reason = f"protected_scope:{proposal.scope.value}"
        elif not proposal.reversible:
            status = OptimizationStatus.REJECTED_NOT_REVERSIBLE
            reason = "proposal_is_not_reversible"
        elif not allowlisted:
            status = OptimizationStatus.REJECTED_OUTSIDE_ALLOWLIST
            reason = "proposal_changes_non_allowlisted_parameters"
        elif improved_families < 3:
            status = OptimizationStatus.REJECTED_INSUFFICIENT_IMPROVEMENT
            reason = "fewer_than_three_independent_families_improved"
        elif (
            candidate_pass_eight < baseline_pass_eight
            or candidate_guardrails.task_accuracy < baseline_guardrails.task_accuracy
            or candidate_guardrails.grounding_rate < baseline_guardrails.grounding_rate
            or candidate_guardrails.critical_safety_rate
            < baseline_guardrails.critical_safety_rate
        ):
            status = OptimizationStatus.REJECTED_REGRESSION
            reason = "repeated_run_or_guardrail_regression"
        else:
            status = OptimizationStatus.APPROVED
            reason = None

        approved = (
            proposal.candidate_parameters
            if status == OptimizationStatus.APPROVED
            else proposal.baseline_parameters
        )
        provenance_ids = tuple(
            dict.fromkeys(
                (
                    *proposal.provenance_ids,
                    *(
                        value
                        for trajectory in guardrail_trajectories
                        for value in trajectory.provenance_ids
                    ),
                )
            )
        )
        material = "|".join(
            (
                dataset_version,
                proposal.proposal_id,
                status.value,
                approved.parameter_set_id,
                *proposal.target_ids,
            )
        )
        return AutonomousOptimizationRelease(
            release_id=(
                f"autonomous-optimization:"
                f"{sha256(material.encode('utf-8')).hexdigest()[:24]}"
            ),
            dataset_version=dataset_version,
            status=status,
            proposal=proposal,
            approved_parameters=approved,
            family_evaluations=family_evaluations,
            baseline_guardrail_evaluation=baseline_guardrails,
            candidate_guardrail_evaluation=candidate_guardrails,
            baseline_pass_eight=baseline_pass_eight,
            candidate_pass_eight=candidate_pass_eight,
            rejection_reason=reason,
            rollback_restored=status != OptimizationStatus.APPROVED,
            provenance_ids=provenance_ids,
        )


def _changes_only_attenuated_signal_boost(proposal: OptimizationProposal) -> bool:
    baseline = proposal.baseline_parameters
    candidate = proposal.candidate_parameters
    return (
        candidate.parameter_set_id != baseline.parameter_set_id
        and candidate.attenuated_signal_boost != baseline.attenuated_signal_boost
        and candidate.evidence_gap_weight == baseline.evidence_gap_weight
        and candidate.material_conflict_weight == baseline.material_conflict_weight
        and candidate.multimodal_review_weight == baseline.multimodal_review_weight
        and candidate.routine_monitoring_weight == baseline.routine_monitoring_weight
        and not candidate.source_authority_mutable
        and not candidate.permission_mutable
        and not candidate.safety_threshold_mutable
    )


def _pass_eight(
    parameters: AnalyticalTuningParameters,
    trajectories: tuple[LearningTrajectory, ...],
) -> float:
    ranker = AnalyticalFollowupRanker(parameters)
    successes: dict[str, list[bool]] = {item.trajectory_id: [] for item in trajectories}
    for run in range(8):
        ordered = trajectories if run % 2 == 0 else tuple(reversed(trajectories))
        for item in ordered:
            prediction = ranker.select(
                evidence_gap_signal=item.evidence_gap_signal,
                material_conflict_signal=item.material_conflict_signal,
                multimodal_signal=item.multimodal_signal,
                routine_signal=item.routine_signal,
            )
            successes[item.trajectory_id].append(prediction == item.gold_focus)
    return sum(all(results) for results in successes.values()) / len(successes)
