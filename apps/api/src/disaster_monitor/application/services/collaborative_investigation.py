"""Bounded deterministic collaboration over immutable trusted artifacts."""

from collections import defaultdict
from hashlib import sha256

from disaster_monitor.application.services.coordination_handoffs import (
    validate_specialist_handoff,
)
from disaster_monitor.domain.coordination import (
    CollaborativeInvestigation,
    CollaborativeInvestigationStatus,
    SpecialistFinding,
    SpecialistHandoff,
    SpecialistRole,
)
from disaster_monitor.domain.decision import (
    PROHIBITED_CONSEQUENTIAL_ACTIONS,
    DecisionSupportArtifact,
)
from disaster_monitor.domain.disaster import (
    EvidenceAvailability,
    EvidenceDisposition,
    EvidenceWorldState,
)
from disaster_monitor.domain.multimodal import MultimodalEvidenceState

SAFETY_POLICY_FINGERPRINT = sha256(
    "|".join(PROHIBITED_CONSEQUENTIAL_ACTIONS).encode("utf-8")
).hexdigest()[:24]


class CollaborativeInvestigator:
    """Merge specialist findings or retain the bounded single-supervisor path."""

    def investigate(
        self,
        state: EvidenceWorldState,
        handoffs: tuple[SpecialistHandoff, ...],
        *,
        decision_support: DecisionSupportArtifact | None = None,
        multimodal_state: MultimodalEvidenceState | None = None,
        injected_findings: tuple[SpecialistFinding, ...] = (),
        requested_iterations: int = 1,
    ) -> CollaborativeInvestigation:
        if requested_iterations > 2 or requested_iterations < 1:
            return _fallback(
                state,
                handoffs,
                reason="iteration_budget_exceeded",
                iterations=2,
            )
        try:
            for handoff in handoffs:
                validate_specialist_handoff(handoff)
        except ValueError:
            return _fallback(
                state,
                handoffs,
                reason="invalid_handoff",
                iterations=requested_iterations,
            )
        roles = tuple(dict.fromkeys(item.receiver_role for item in handoffs))
        if len(roles) < 2:
            return _fallback(
                state,
                handoffs,
                reason="insufficient_specialists",
                iterations=requested_iterations,
            )

        findings: list[SpecialistFinding] = []
        if SpecialistRole.EVIDENCE_RECONCILIATION in roles:
            findings.extend(_evidence_findings(state, decision_support))
        if SpecialistRole.DECISION_ANALYSIS in roles:
            if decision_support is None:
                return _fallback(
                    state,
                    handoffs,
                    reason="missing_decision_artifact",
                    iterations=requested_iterations,
                )
            findings.extend(_decision_findings(decision_support))
        if SpecialistRole.MULTIMODAL_ANALYSIS in roles:
            if multimodal_state is None:
                return _fallback(
                    state,
                    handoffs,
                    reason="missing_multimodal_artifact",
                    iterations=requested_iterations,
                )
            findings.extend(_multimodal_findings(multimodal_state))
        findings.extend(injected_findings)
        ordered = tuple(
            sorted(
                findings,
                key=lambda item: (
                    item.finding_key,
                    item.value,
                    item.specialist_role.value,
                    item.finding_id,
                ),
            )
        )
        known_evidence, known_sources = _known_provenance(
            state, decision_support, multimodal_state
        )
        if any(
            item.specialist_role not in roles
            or item.state_version != state.state_version
            or not set(item.evidence_ids) <= known_evidence
            or not set(item.source_ids) <= known_sources
            or item.safety_policy_fingerprint != SAFETY_POLICY_FINGERPRINT
            for item in ordered
        ):
            return _fallback(
                state,
                handoffs,
                reason="finding_authority_or_provenance_violation",
                iterations=requested_iterations,
            )
        values_by_key: dict[str, set[str]] = defaultdict(set)
        for finding in ordered:
            values_by_key[finding.finding_key].add(finding.value)
        deadlocks = tuple(
            sorted(key for key, values in values_by_key.items() if len(values) > 1)
        )
        if deadlocks:
            return _fallback(
                state,
                handoffs,
                reason="specialist_deadlock",
                iterations=requested_iterations,
                deadlocks=deadlocks,
            )
        material = "|".join(
            (
                state.state_version,
                *(item.handoff_id for item in handoffs),
                *(f"{item.finding_key}:{item.value}" for item in ordered),
            )
        )
        result = CollaborativeInvestigation(
            investigation_id=(
                f"collaboration:{sha256(material.encode('utf-8')).hexdigest()[:24]}"
            ),
            status=CollaborativeInvestigationStatus.COMPLETED,
            evidence_state_version=state.state_version,
            handoff_ids=tuple(item.handoff_id for item in handoffs),
            findings=ordered,
            participating_roles=roles,
            unresolved_deadlocks=(),
            iterations=requested_iterations,
            safety_policy_fingerprint=SAFETY_POLICY_FINGERPRINT,
            fallback_reason=None,
        )
        validate_collaborative_investigation(
            result,
            state=state,
            decision_support=decision_support,
            multimodal_state=multimodal_state,
        )
        return result


def validate_collaborative_investigation(
    result: CollaborativeInvestigation,
    *,
    state: EvidenceWorldState,
    decision_support: DecisionSupportArtifact | None,
    multimodal_state: MultimodalEvidenceState | None,
) -> None:
    if result.evidence_state_version != state.state_version:
        raise ValueError("Collaboration escaped canonical evidence state.")
    if result.safety_policy_fingerprint != SAFETY_POLICY_FINGERPRINT:
        raise ValueError("Collaboration altered deterministic safety policy.")
    known_evidence, known_sources = _known_provenance(
        state, decision_support, multimodal_state
    )
    if any(
        finding.state_version != state.state_version
        or not set(finding.evidence_ids) <= known_evidence
        or not set(finding.source_ids) <= known_sources
        or finding.safety_policy_fingerprint != SAFETY_POLICY_FINGERPRINT
        for finding in result.findings
    ):
        raise ValueError("Collaborative finding mutated or invented evidence.")


def single_supervisor_baseline(state: EvidenceWorldState) -> dict[str, str]:
    """Frozen pre-collaboration structured end state for benchmark comparison."""
    return {"event_identity": state.physical_event.physical_event_id}


def single_supervisor_fallback(
    state: EvidenceWorldState,
    handoffs: tuple[SpecialistHandoff, ...],
    *,
    reason: str,
    iterations: int = 1,
) -> CollaborativeInvestigation:
    """Create the explicit safe fallback retained by the supervisor."""
    return _fallback(
        state,
        handoffs,
        reason=reason,
        iterations=max(1, min(iterations, 2)),
    )


def render_collaborative_investigation(result: CollaborativeInvestigation) -> str:
    if result.status == CollaborativeInvestigationStatus.SINGLE_SUPERVISOR_FALLBACK:
        return (
            "Coordination retained the bounded single-supervisor path: "
            f"{result.fallback_reason}."
        )
    lines = [
        "Bounded specialist collaboration completed without changing evidence or "
        "safety policy."
    ]
    lines.extend(f"- {item.summary}" for item in result.findings)
    return "\n".join(lines)


def _evidence_findings(
    state: EvidenceWorldState, decision_support: DecisionSupportArtifact | None
) -> tuple[SpecialistFinding, ...]:
    base_evidence = (state.physical_event.physical_event_id,)
    base_sources = (state.physical_event.event.source.source_id,)
    findings = [
        _finding(
            SpecialistRole.EVIDENCE_RECONCILIATION,
            "event_identity",
            state.physical_event.physical_event_id,
            "Evidence specialist retained the selected physical-event identity.",
            state.state_version,
            base_evidence,
            base_sources,
        )
    ]
    gap_count = (
        len(decision_support.evidence_gaps)
        if decision_support is not None
        else sum(
            claim.availability == EvidenceAvailability.ABSENT for claim in state.claims
        )
    )
    findings.append(
        _finding(
            SpecialistRole.EVIDENCE_RECONCILIATION,
            "evidence_gap_count",
            str(gap_count),
            f"Evidence specialist retained {gap_count} visible evidence gap(s).",
            state.state_version,
            base_evidence,
            base_sources,
        )
    )
    for claim in state.claims:
        conflicting = tuple(
            item.observation
            for item in claim.history
            if item.disposition == EvidenceDisposition.CONFLICTING
        )
        if not conflicting:
            continue
        current = () if claim.current is None else (claim.current,)
        observations = tuple(dict.fromkeys((*current, *conflicting)))
        findings.append(
            _finding(
                SpecialistRole.EVIDENCE_RECONCILIATION,
                f"claim:{claim.claim_key}:conflict",
                "retained",
                f"Evidence specialist retained the {claim.claim_key} conflict.",
                state.state_version,
                tuple(item.observation_id for item in observations),
                tuple(
                    dict.fromkeys(item.fact.source.source_id for item in observations)
                ),
            )
        )
    return tuple(findings)


def _decision_findings(
    artifact: DecisionSupportArtifact,
) -> tuple[SpecialistFinding, ...]:
    evidence_ids = tuple(
        dict.fromkeys(
            evidence_id for fact in artifact.facts for evidence_id in fact.evidence_ids
        )
    )
    source_ids = tuple(
        dict.fromkeys(
            source_id for fact in artifact.facts for source_id in fact.source_ids
        )
    )
    recommendation = artifact.scenario_analysis.recommendation
    findings = [
        _finding(
            SpecialistRole.DECISION_ANALYSIS,
            "decision_policy",
            SAFETY_POLICY_FINGERPRINT,
            "Decision specialist verified the unchanged closed safety policy.",
            artifact.evidence_state_version,
            evidence_ids,
            source_ids,
        ),
        _finding(
            SpecialistRole.DECISION_ANALYSIS,
            "scenario_mode",
            artifact.scenario_analysis.mode.value,
            "Decision specialist retained the calibrated scenario mode.",
            artifact.evidence_state_version,
            evidence_ids,
            source_ids,
        ),
        _finding(
            SpecialistRole.DECISION_ANALYSIS,
            "recommendation_status",
            recommendation.status.value,
            "Decision specialist retained the recommendation authority state.",
            artifact.evidence_state_version,
            evidence_ids,
            source_ids,
        ),
    ]
    findings.extend(
        _finding(
            SpecialistRole.DECISION_ANALYSIS,
            f"claim:{item.claim_key}:conflict",
            "retained",
            f"Decision specialist retained the {item.claim_key} contradiction.",
            artifact.evidence_state_version,
            item.evidence_ids,
            source_ids,
        )
        for item in artifact.contradictions
    )
    return tuple(findings)


def _multimodal_findings(
    state: MultimodalEvidenceState,
) -> tuple[SpecialistFinding, ...]:
    evidence_ids = tuple(
        dict.fromkeys(
            (
                *(item.observation_id for item in state.observations),
                *(item.asset_id for item in state.assets),
            )
        )
    )
    source_ids = tuple(dict.fromkeys(item.source.source_id for item in state.assets))
    return (
        _finding(
            SpecialistRole.MULTIMODAL_ANALYSIS,
            "multimodal_provenance",
            state.state_version,
            "Multimodal specialist retained asset and observation provenance.",
            state.evidence_world_state_version,
            evidence_ids,
            source_ids,
        ),
        _finding(
            SpecialistRole.MULTIMODAL_ANALYSIS,
            "visual_observation_count",
            str(len(state.observations)),
            "Multimodal specialist reported the bounded analytical observation count.",
            state.evidence_world_state_version,
            evidence_ids,
            source_ids,
        ),
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


def _finding(
    role: SpecialistRole,
    key: str,
    value: str,
    summary: str,
    state_version: str,
    evidence_ids: tuple[str, ...],
    source_ids: tuple[str, ...],
) -> SpecialistFinding:
    material = "|".join((role.value, key, value, state_version, *evidence_ids))
    return SpecialistFinding(
        finding_id=(f"finding:{sha256(material.encode('utf-8')).hexdigest()[:24]}"),
        specialist_role=role,
        finding_key=key,
        value=value,
        summary=summary,
        state_version=state_version,
        evidence_ids=evidence_ids,
        source_ids=source_ids,
        safety_policy_fingerprint=SAFETY_POLICY_FINGERPRINT,
    )


def _fallback(
    state: EvidenceWorldState,
    handoffs: tuple[SpecialistHandoff, ...],
    *,
    reason: str,
    iterations: int,
    deadlocks: tuple[str, ...] = (),
) -> CollaborativeInvestigation:
    material = "|".join(
        (state.state_version, reason, *(item.handoff_id for item in handoffs))
    )
    return CollaborativeInvestigation(
        investigation_id=(
            f"collaboration:{sha256(material.encode('utf-8')).hexdigest()[:24]}"
        ),
        status=CollaborativeInvestigationStatus.SINGLE_SUPERVISOR_FALLBACK,
        evidence_state_version=state.state_version,
        handoff_ids=tuple(item.handoff_id for item in handoffs),
        findings=(),
        participating_roles=tuple(
            dict.fromkeys(item.receiver_role for item in handoffs)
        ),
        unresolved_deadlocks=deadlocks,
        iterations=iterations,
        safety_policy_fingerprint=SAFETY_POLICY_FINGERPRINT,
        fallback_reason=reason,
    )
