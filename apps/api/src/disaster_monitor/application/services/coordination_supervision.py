"""Budgeted autonomous coordination with explicit sufficiency and termination."""

from hashlib import sha256

from disaster_monitor.application.services.collaborative_investigation import (
    SAFETY_POLICY_FINGERPRINT,
    CollaborativeInvestigator,
    single_supervisor_fallback,
    validate_collaborative_investigation,
)
from disaster_monitor.domain.coordination import (
    CollaborativeInvestigationStatus,
    CoordinationSupervision,
    CoordinationSupervisorStatus,
    SpecialistFinding,
    SpecialistHandoff,
)
from disaster_monitor.domain.decision import DecisionSupportArtifact
from disaster_monitor.domain.disaster import EvidenceDisposition, EvidenceWorldState
from disaster_monitor.domain.multimodal import MultimodalEvidenceState


class CoordinationSupervisor:
    """Keep the completed default plan on any unsafe collaborative end state."""

    def __init__(
        self,
        *,
        investigator: CollaborativeInvestigator | None = None,
        max_handoffs: int = 4,
        max_findings: int = 24,
        max_iterations: int = 2,
    ) -> None:
        if min(max_handoffs, max_findings, max_iterations) <= 0:
            raise ValueError("Coordination supervisor budgets must be positive.")
        self._investigator = investigator or CollaborativeInvestigator()
        self._max_handoffs = max_handoffs
        self._max_findings = max_findings
        self._max_iterations = max_iterations

    def run(
        self,
        state: EvidenceWorldState,
        handoffs: tuple[SpecialistHandoff, ...],
        *,
        decision_support: DecisionSupportArtifact | None = None,
        multimodal_state: MultimodalEvidenceState | None = None,
        injected_findings: tuple[SpecialistFinding, ...] = (),
        requested_iterations: int = 1,
    ) -> CoordinationSupervision:
        fallback_override: str | None = None
        if len(handoffs) > self._max_handoffs:
            fallback_override = "handoff_budget_exceeded"
            collaboration = single_supervisor_fallback(
                state,
                handoffs,
                reason=fallback_override,
                iterations=requested_iterations,
            )
        elif requested_iterations > self._max_iterations or requested_iterations < 1:
            fallback_override = "iteration_budget_exceeded"
            collaboration = single_supervisor_fallback(
                state,
                handoffs,
                reason=fallback_override,
                iterations=requested_iterations,
            )
        else:
            collaboration = self._investigator.investigate(
                state,
                handoffs,
                decision_support=decision_support,
                multimodal_state=multimodal_state,
                injected_findings=injected_findings,
                requested_iterations=requested_iterations,
            )
        if len(collaboration.findings) > self._max_findings:
            fallback_override = "finding_budget_exceeded"
            collaboration = single_supervisor_fallback(
                state,
                handoffs,
                reason=fallback_override,
                iterations=collaboration.iterations,
            )
        if collaboration.safety_policy_fingerprint != SAFETY_POLICY_FINGERPRINT:
            fallback_override = "safety_policy_violation"
            collaboration = single_supervisor_fallback(
                state,
                handoffs,
                reason=fallback_override,
                iterations=collaboration.iterations,
            )

        required = _required_findings(state, decision_support, multimodal_state)
        actual = {item.finding_key for item in collaboration.findings}
        missing = tuple(key for key in required if key not in actual)
        sufficient = (
            collaboration.status == CollaborativeInvestigationStatus.COMPLETED
            and not missing
            and len(handoffs) <= self._max_handoffs
            and len(collaboration.findings) <= self._max_findings
            and collaboration.iterations <= self._max_iterations
            and collaboration.safety_policy_fingerprint == SAFETY_POLICY_FINGERPRINT
        )
        if sufficient:
            status = CoordinationSupervisorStatus.AUTONOMOUS_COMPLETE
            reason = "sufficient_analytical_end_state"
            rationale = (
                "The bounded specialist artifacts satisfy every declared finding key; "
                "coordination terminated without changing evidence, permissions, or "
                "safety policy."
            )
        else:
            status = CoordinationSupervisorStatus.DEFAULT_PLAN_FALLBACK
            cause = (
                fallback_override
                or collaboration.fallback_reason
                or "insufficient_finding_set"
            )
            reason = f"default_plan_{cause}"
            rationale = (
                "The collaborative end state did not satisfy the bounded supervisor "
                f"gate ({cause}); the completed default plan remains authoritative."
            )
        evidence_ids, source_ids = _result_provenance(state, collaboration.findings)
        material = "|".join(
            (
                state.state_version,
                collaboration.investigation_id,
                status.value,
                reason,
                *required,
                *missing,
            )
        )
        supervision = CoordinationSupervision(
            supervision_id=(
                "coordination-supervision:"
                f"{sha256(material.encode('utf-8')).hexdigest()[:24]}"
            ),
            status=status,
            evidence_state_version=state.state_version,
            collaboration=collaboration,
            sufficient=sufficient,
            required_finding_keys=required,
            missing_finding_keys=missing,
            evidence_ids=evidence_ids,
            source_ids=source_ids,
            final_rationale=rationale,
            termination_reason=reason,
            handoff_count=len(handoffs),
            finding_count=len(collaboration.findings),
            iterations=collaboration.iterations,
            max_handoffs=self._max_handoffs,
            max_findings=self._max_findings,
            max_iterations=self._max_iterations,
            safety_policy_fingerprint=SAFETY_POLICY_FINGERPRINT,
        )
        validate_coordination_supervision(
            supervision,
            state=state,
            decision_support=decision_support,
            multimodal_state=multimodal_state,
        )
        return supervision


def validate_coordination_supervision(
    supervision: CoordinationSupervision,
    *,
    state: EvidenceWorldState,
    decision_support: DecisionSupportArtifact | None,
    multimodal_state: MultimodalEvidenceState | None,
) -> None:
    if supervision.evidence_state_version != state.state_version:
        raise ValueError("Coordination supervisor escaped canonical evidence state.")
    if supervision.safety_policy_fingerprint != SAFETY_POLICY_FINGERPRINT:
        raise ValueError("Coordination supervisor altered deterministic safety policy.")
    validate_collaborative_investigation(
        supervision.collaboration,
        state=state,
        decision_support=decision_support,
        multimodal_state=multimodal_state,
    )
    required = _required_findings(state, decision_support, multimodal_state)
    if supervision.required_finding_keys != required:
        raise ValueError("Coordination supervisor changed its sufficiency checklist.")
    known_evidence, known_sources = _known_provenance(
        state, decision_support, multimodal_state
    )
    if (
        not set(supervision.evidence_ids) <= known_evidence
        or not set(supervision.source_ids) <= known_sources
    ):
        raise ValueError("Coordination supervisor exposed unknown provenance.")


def render_coordination_supervision(supervision: CoordinationSupervision) -> str:
    checklist = (
        "complete"
        if not supervision.missing_finding_keys
        else "missing " + ", ".join(supervision.missing_finding_keys)
    )
    return (
        f"Supervisor status: {supervision.status.value}; sufficiency checklist: "
        f"{checklist}; termination: {supervision.termination_reason}. "
        f"{supervision.final_rationale}"
    )


def _required_findings(
    state: EvidenceWorldState,
    decision_support: DecisionSupportArtifact | None,
    multimodal_state: MultimodalEvidenceState | None,
) -> tuple[str, ...]:
    keys = ["event_identity", "evidence_gap_count"]
    if decision_support is not None:
        keys.extend(("decision_policy", "scenario_mode", "recommendation_status"))
    keys.extend(
        f"claim:{claim.claim_key}:conflict"
        for claim in state.claims
        if any(
            item.disposition == EvidenceDisposition.CONFLICTING
            for item in claim.history
        )
    )
    if multimodal_state is not None:
        keys.extend(("multimodal_provenance", "visual_observation_count"))
    return tuple(dict.fromkeys(keys))


def _result_provenance(
    state: EvidenceWorldState, findings: tuple[SpecialistFinding, ...]
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    if findings:
        return (
            tuple(
                dict.fromkeys(
                    evidence_id
                    for finding in findings
                    for evidence_id in finding.evidence_ids
                )
            ),
            tuple(
                dict.fromkeys(
                    source_id
                    for finding in findings
                    for source_id in finding.source_ids
                )
            ),
        )
    return (
        (state.physical_event.physical_event_id,),
        (state.physical_event.event.source.source_id,),
    )


def _known_provenance(
    state: EvidenceWorldState,
    decision_support: DecisionSupportArtifact | None,
    multimodal_state: MultimodalEvidenceState | None,
) -> tuple[set[str], set[str]]:
    evidence_ids = {
        state.physical_event.physical_event_id,
        *(
            item.observation.observation_id
            for claim in state.claims
            for item in claim.history
        ),
    }
    source_ids = {
        state.physical_event.event.source.source_id,
        *(
            item.observation.fact.source.source_id
            for claim in state.claims
            for item in claim.history
        ),
    }
    if decision_support is not None:
        evidence_ids.update(
            evidence_id
            for fact in decision_support.facts
            for evidence_id in fact.evidence_ids
        )
        source_ids.update(
            source_id
            for fact in decision_support.facts
            for source_id in fact.source_ids
        )
    if multimodal_state is not None:
        evidence_ids.update(item.asset_id for item in multimodal_state.assets)
        evidence_ids.update(
            item.observation_id for item in multimodal_state.observations
        )
        source_ids.update(item.source.source_id for item in multimodal_state.assets)
    return evidence_ids, source_ids
