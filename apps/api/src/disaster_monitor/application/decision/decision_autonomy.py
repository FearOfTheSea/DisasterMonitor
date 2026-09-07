"""State-bounded autonomy for reversible internal decision-support options."""

from dataclasses import replace
from hashlib import sha256

from disaster_monitor.domain.decision import (
    PROHIBITED_CONSEQUENTIAL_ACTIONS,
    DecisionAutonomyMode,
    DecisionConsequence,
    DecisionExecutionOutcome,
    DecisionExecutionState,
    DecisionInternalAction,
    DecisionRecommendationStatus,
    DecisionSupportArtifact,
)

_ACTION_BY_OPTION_KIND = {
    DecisionInternalAction.CONTINUE_APPROVED_MONITORING.value: (
        DecisionInternalAction.CONTINUE_APPROVED_MONITORING
    ),
    DecisionInternalAction.PRIORITIZE_EVIDENCE_GAPS.value: (
        DecisionInternalAction.PRIORITIZE_EVIDENCE_GAPS
    ),
    DecisionInternalAction.COMPARE_VERIFIED_UPDATES.value: (
        DecisionInternalAction.COMPARE_VERIFIED_UPDATES
    ),
}


class DecisionAutonomyController:
    """Apply only a selected eligible option to request-scoped internal state."""

    def __init__(self, *, autonomy_enabled: bool = True) -> None:
        self._autonomy_enabled = autonomy_enabled

    def execute(
        self,
        artifact: DecisionSupportArtifact,
        *,
        initial_state: DecisionExecutionState | None = None,
        requested_action: str | None = None,
    ) -> DecisionExecutionOutcome:
        initial = initial_state or DecisionExecutionState(
            artifact_id=artifact.artifact_id
        )
        if initial.artifact_id != artifact.artifact_id:
            raise ValueError(
                "Decision execution initial state escaped artifact lineage."
            )
        recommendation = artifact.scenario_analysis.recommendation
        if requested_action in PROHIBITED_CONSEQUENTIAL_ACTIONS:
            return _advisory(
                artifact,
                initial,
                requires_human=True,
                rule_ids=(
                    "ds.autonomy.prohibited_action_downgrade",
                    "ds.autonomy.advisory_only",
                ),
                reason="advisory_prohibited_action_downgrade",
            )
        if not self._autonomy_enabled:
            return _advisory(
                artifact,
                initial,
                requires_human=True,
                rule_ids=(
                    "ds.autonomy.rollback_disabled",
                    "ds.autonomy.advisory_only",
                ),
                reason="advisory_autonomy_disabled",
            )
        if recommendation.status != DecisionRecommendationStatus.AVAILABLE:
            return _advisory(
                artifact,
                initial,
                requires_human=(
                    recommendation.status
                    == DecisionRecommendationStatus.HUMAN_REVIEW_REQUIRED
                ),
                rule_ids=(
                    "ds.autonomy.recommendation_unavailable",
                    "ds.autonomy.advisory_only",
                ),
                reason="advisory_recommendation_unavailable",
            )

        option = next(
            (
                item
                for item in artifact.options
                if item.option_id == recommendation.option_id
            ),
            None,
        )
        selected_action = None if option is None else option.option_kind
        if requested_action is not None and requested_action != selected_action:
            return _advisory(
                artifact,
                initial,
                requires_human=True,
                rule_ids=(
                    "ds.autonomy.unselected_action_downgrade",
                    "ds.autonomy.advisory_only",
                ),
                reason="advisory_unselected_action_downgrade",
            )
        action = _ACTION_BY_OPTION_KIND.get(selected_action or "")
        if (
            option is None
            or action is None
            or not option.reversible
            or option.requires_human_approval
            or option.consequence == DecisionConsequence.HIGH
            or option.prohibited_actions != PROHIBITED_CONSEQUENTIAL_ACTIONS
            or recommendation.policy_constraints != PROHIBITED_CONSEQUENTIAL_ACTIONS
            or recommendation.unsupported_premise_ids
        ):
            return _advisory(
                artifact,
                initial,
                requires_human=True,
                rule_ids=(
                    "ds.autonomy.authority_guard_downgrade",
                    "ds.autonomy.advisory_only",
                ),
                reason="advisory_authority_guard_downgrade",
            )

        final = _apply(initial, action)
        rules = (
            "ds.autonomy.selected_option_only",
            "ds.autonomy.reversible_internal_only",
            "ds.autonomy.no_consequential_actions",
        )
        outcome = DecisionExecutionOutcome(
            execution_id=_id(
                artifact.artifact_id,
                str(initial.revision),
                DecisionAutonomyMode.AUTONOMOUS_INTERNAL.value,
                action.value,
                *rules,
            ),
            artifact_id=artifact.artifact_id,
            autonomy_mode=DecisionAutonomyMode.AUTONOMOUS_INTERNAL,
            action=action,
            selected_option_id=option.option_id,
            initial_state=initial,
            final_state=final,
            reversible=True,
            requires_human_intervention=False,
            policy_rule_ids=rules,
            termination_reason="autonomous_internal_complete",
        )
        validate_decision_execution(outcome, artifact)
        return outcome


def validate_decision_execution(
    outcome: DecisionExecutionOutcome, artifact: DecisionSupportArtifact
) -> None:
    if outcome.artifact_id != artifact.artifact_id:
        raise ValueError("Decision outcome escaped artifact lineage.")
    if (
        outcome.final_state.public_warning_issued
        or outcome.final_state.evacuation_directive_issued
        or outcome.final_state.resource_allocation_ordered
    ):
        raise ValueError("Decision outcome contains prohibited consequential effects.")
    if outcome.autonomy_mode == DecisionAutonomyMode.ADVISORY_ONLY:
        if outcome.final_state != outcome.initial_state:
            raise ValueError("Advisory-only outcome changed system state.")
        return
    option = next(
        (
            item
            for item in artifact.options
            if item.option_id == outcome.selected_option_id
        ),
        None,
    )
    if (
        option is None
        or option.option_kind != outcome.action.value
        or not option.reversible
        or option.requires_human_approval
        or option.consequence == DecisionConsequence.HIGH
        or option.prohibited_actions != PROHIBITED_CONSEQUENTIAL_ACTIONS
    ):
        raise ValueError("Autonomous outcome applied an ineligible option.")
    expected = _apply(outcome.initial_state, outcome.action)
    if outcome.final_state != expected:
        raise ValueError("Autonomous outcome has an incorrect final system state.")


def render_decision_execution(outcome: DecisionExecutionOutcome) -> str:
    if outcome.autonomy_mode == DecisionAutonomyMode.ADVISORY_ONLY:
        return (
            "Bounded decision state: advisory-only; no internal or external state "
            f"changed ({outcome.termination_reason})."
        )
    return (
        "Bounded decision state: applied reversible internal action "
        f"{outcome.action.value}; external warnings, evacuation directives, and "
        "resource orders remain unavailable."
    )


def _advisory(
    artifact: DecisionSupportArtifact,
    initial: DecisionExecutionState,
    *,
    requires_human: bool,
    rule_ids: tuple[str, ...],
    reason: str,
) -> DecisionExecutionOutcome:
    outcome = DecisionExecutionOutcome(
        execution_id=_id(
            artifact.artifact_id,
            str(initial.revision),
            DecisionAutonomyMode.ADVISORY_ONLY.value,
            reason,
            *rule_ids,
        ),
        artifact_id=artifact.artifact_id,
        autonomy_mode=DecisionAutonomyMode.ADVISORY_ONLY,
        action=DecisionInternalAction.NONE,
        selected_option_id=None,
        initial_state=initial,
        final_state=initial,
        reversible=True,
        requires_human_intervention=requires_human,
        policy_rule_ids=rule_ids,
        termination_reason=reason,
    )
    validate_decision_execution(outcome, artifact)
    return outcome


def _apply(
    state: DecisionExecutionState, action: DecisionInternalAction
) -> DecisionExecutionState:
    if action == DecisionInternalAction.CONTINUE_APPROVED_MONITORING:
        return replace(state, revision=state.revision + 1, monitoring_active=True)
    if action == DecisionInternalAction.PRIORITIZE_EVIDENCE_GAPS:
        return replace(
            state,
            revision=state.revision + 1,
            evidence_gap_priority_active=True,
        )
    if action == DecisionInternalAction.COMPARE_VERIFIED_UPDATES:
        return replace(
            state,
            revision=state.revision + 1,
            verified_update_comparison_active=True,
        )
    raise ValueError("Decision autonomy cannot apply a non-internal action.")


def _id(*values: str) -> str:
    material = "|".join(values)
    return f"decision-execution:{sha256(material.encode('utf-8')).hexdigest()[:24]}"
