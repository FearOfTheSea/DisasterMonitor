"""Consequence-bounded authority policy for reversible internal triage."""

from hashlib import sha256

from disaster_monitor.domain.disaster import (
    IncidentPriority,
    IncidentPriorityAssessment,
    InternalTriageAction,
    InternalTriageDecision,
    TriageAutonomyMode,
)


class TriageAutonomyPolicy:
    """Permit autonomy only for declared low/moderate internal actions."""

    def __init__(self, *, autonomy_enabled: bool = True) -> None:
        self._autonomy_enabled = autonomy_enabled

    def is_eligible(self, assessment: IncidentPriorityAssessment) -> bool:
        return (
            assessment.priority in {IncidentPriority.LOW, IncidentPriority.MODERATE}
            and not assessment.requires_human_review
        )

    def decide(self, assessment: IncidentPriorityAssessment) -> InternalTriageDecision:
        rules: tuple[str, ...]
        if assessment.priority == IncidentPriority.CRITICAL:
            action = InternalTriageAction.ESCALATE_CRITICAL
            mode = TriageAutonomyMode.HUMAN_IN_THE_LOOP
            requires_human = True
            rules = (
                "tr.autonomy.critical_requires_human",
                "tr.autonomy.no_incident_suppression",
            )
        elif assessment.priority == IncidentPriority.HIGH:
            action = InternalTriageAction.REQUEST_PRIORITY_REVIEW
            mode = TriageAutonomyMode.HUMAN_ON_THE_LOOP
            requires_human = True
            rules = (
                "tr.autonomy.high_requires_review",
                "tr.autonomy.no_incident_suppression",
            )
        elif assessment.requires_human_review:
            action = InternalTriageAction.REQUEST_PRIORITY_REVIEW
            mode = TriageAutonomyMode.HUMAN_ON_THE_LOOP
            requires_human = True
            rules = (
                "tr.autonomy.uncertainty_requires_review",
                "tr.autonomy.no_incident_suppression",
            )
        elif self._autonomy_enabled:
            action = (
                InternalTriageAction.MONITOR_INTERNAL
                if assessment.priority == IncidentPriority.LOW
                else InternalTriageAction.QUEUE_INTERNAL
            )
            mode = TriageAutonomyMode.AUTONOMOUS_INTERNAL
            requires_human = False
            rules = (
                "tr.autonomy.low_moderate_internal_only",
                "tr.autonomy.reversible_actions_only",
                "tr.autonomy.no_incident_suppression",
            )
        else:
            action = InternalTriageAction.REQUEST_PRIORITY_REVIEW
            mode = TriageAutonomyMode.HUMAN_ON_THE_LOOP
            requires_human = True
            rules = (
                "tr.autonomy.rollback_human_review",
                "tr.autonomy.no_incident_suppression",
            )

        material = "|".join(
            (
                assessment.assessment_id,
                action.value,
                mode.value,
                *rules,
            )
        )
        decision_id = f"triage:{sha256(material.encode('utf-8')).hexdigest()[:24]}"
        return InternalTriageDecision(
            decision_id=decision_id,
            assessment_id=assessment.assessment_id,
            physical_event_id=assessment.physical_event_id,
            evidence_state_version=assessment.evidence_state_version,
            priority=assessment.priority,
            action=action,
            autonomy_mode=mode,
            reversible=True,
            requires_human_intervention=requires_human,
            policy_rule_ids=rules,
            decided_at=assessment.assessed_at,
        )
