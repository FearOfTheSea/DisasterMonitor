"""Sequential specialist execution with atomic deterministic validation."""

from dataclasses import dataclass
from hashlib import sha256
from time import perf_counter

from disaster_monitor.application.agent.models import (
    SpecialistArtifactProjection,
    SpecialistProjectionItem,
)
from disaster_monitor.application.ports.specialist_model import (
    SpecialistModel,
    SpecialistModelRequest,
)
from disaster_monitor.application.services.collaborative_investigation import (
    SAFETY_POLICY_FINGERPRINT,
)
from disaster_monitor.application.services.coordination_handoffs import (
    task_owner,
    validate_specialist_handoff,
)
from disaster_monitor.domain.coordination import (
    SpecialistFinding,
    SpecialistFindingDraft,
    SpecialistHandoff,
    SpecialistRole,
)
from disaster_monitor.domain.decision import DecisionSupportArtifact
from disaster_monitor.domain.disaster import (
    EvidenceAvailability,
    EvidenceDisposition,
    EvidenceWorldState,
)
from disaster_monitor.domain.memory import MemoryContextArtifact

SUPPORTED_LLM_SPECIALISTS = (
    SpecialistRole.EVIDENCE_RECONCILIATION,
    SpecialistRole.DECISION_ANALYSIS,
)


@dataclass(frozen=True, slots=True)
class SpecialistExecutionResult:
    findings: tuple[SpecialistFinding, ...]
    model_call_count: int
    fallback_reason: str | None
    provenance_validation_failures: int
    latency_ms: float


class SpecialistExecutor:
    """Run supported specialist calls one at a time and trust none by default."""

    def __init__(
        self,
        model: SpecialistModel | None,
        *,
        max_model_calls: int = 2,
        max_coordination_findings: int = 24,
    ) -> None:
        if not 0 <= max_model_calls <= 2:
            raise ValueError(
                "Specialist model-call limit must be between zero and two."
            )
        if max_coordination_findings <= 0:
            raise ValueError("Coordination finding budget must be positive.")
        self._model = model
        self._max_model_calls = max_model_calls
        self._max_coordination_findings = max_coordination_findings

    async def execute(
        self,
        state: EvidenceWorldState,
        handoffs: tuple[SpecialistHandoff, ...],
        *,
        decision_support: DecisionSupportArtifact | None = None,
        memory_context: MemoryContextArtifact | None = None,
    ) -> SpecialistExecutionResult:
        started = perf_counter()
        if self._model is None or self._max_model_calls == 0:
            return self._result((), 0, None, 0, started)
        supported = tuple(
            handoff
            for role in SUPPORTED_LLM_SPECIALISTS
            for handoff in handoffs
            if handoff.receiver_role is role
        )
        if len(supported) > self._max_model_calls:
            return self._result(
                (), 0, "specialist_model_call_budget_exceeded", 0, started
            )
        expected_count = sum(
            len(_expected_values(state, handoff.receiver_role, decision_support))
            for handoff in handoffs
        )
        if expected_count + len(supported) > self._max_coordination_findings:
            return self._result((), 0, "finding_budget_exceeded", 0, started)

        accepted: list[SpecialistFinding] = []
        model_calls = 0
        for handoff in supported:
            try:
                validate_specialist_handoff(handoff)
                projection = _projection(state, handoff, decision_support)
            except ValueError:
                return self._result((), model_calls, "invalid_handoff", 1, started)
            try:
                model_calls += 1
                draft = await self._model.generate_finding(
                    SpecialistModelRequest(
                        handoff=handoff,
                        artifact=projection,
                        safety_policy_fingerprint=SAFETY_POLICY_FINGERPRINT,
                        memory_context=memory_context,
                    )
                )
            except Exception:
                return self._result(
                    (), model_calls, "specialist_model_failure", 0, started
                )
            reason = _validation_failure(
                draft,
                state=state,
                handoff=handoff,
                projection=projection,
                decision_support=decision_support,
            )
            if reason is not None:
                provenance_failure = int(
                    reason
                    in {
                        "state_version_lineage_violation",
                        "evidence_membership_violation",
                        "source_membership_violation",
                    }
                )
                return self._result(
                    (), model_calls, reason, provenance_failure, started
                )
            accepted.append(_trusted_finding(draft, handoff))
        return self._result(tuple(accepted), model_calls, None, 0, started)

    @staticmethod
    def _result(
        findings: tuple[SpecialistFinding, ...],
        calls: int,
        reason: str | None,
        provenance_failures: int,
        started: float,
    ) -> SpecialistExecutionResult:
        return SpecialistExecutionResult(
            findings=findings,
            model_call_count=calls,
            fallback_reason=reason,
            provenance_validation_failures=provenance_failures,
            latency_ms=max(0.0, (perf_counter() - started) * 1_000),
        )


def _validation_failure(
    draft: SpecialistFindingDraft,
    *,
    state: EvidenceWorldState,
    handoff: SpecialistHandoff,
    projection: SpecialistArtifactProjection,
    decision_support: DecisionSupportArtifact | None,
) -> str | None:
    if (
        draft.specialist_role is not handoff.receiver_role
        or draft.task_type is not handoff.task_type
        or task_owner(draft.task_type) is not draft.specialist_role
    ):
        return "specialist_role_or_task_violation"
    if draft.permissions != handoff.granted_permissions:
        return "permission_escalation"
    if (
        draft.state_version != state.state_version
        or draft.state_version != projection.state_version
        or any(
            reference.state_version != draft.state_version
            for reference in handoff.artifact_references
        )
    ):
        return "state_version_lineage_violation"
    if not set(draft.evidence_ids) <= set(projection.admitted_evidence_ids):
        return "evidence_membership_violation"
    if not set(draft.source_ids) <= set(projection.admitted_source_ids):
        return "source_membership_violation"
    if draft.safety_policy_fingerprint != SAFETY_POLICY_FINGERPRINT:
        return "safety_policy_violation"
    expected = _expected_values(state, draft.specialist_role, decision_support)
    if expected.get(draft.finding_key) != draft.value:
        return "contradictory_specialist_output"
    return None


def _projection(
    state: EvidenceWorldState,
    handoff: SpecialistHandoff,
    decision_support: DecisionSupportArtifact | None,
) -> SpecialistArtifactProjection:
    reference = handoff.artifact_references[0]
    known_evidence, known_sources = _known_provenance(state, decision_support)
    if (
        reference.state_version != state.state_version
        or not set(reference.evidence_ids) <= known_evidence
        or not set(reference.source_ids) <= known_sources
    ):
        raise ValueError("Specialist handoff escaped admitted canonical provenance.")
    values = _expected_values(state, handoff.receiver_role, decision_support)
    items = tuple(
        SpecialistProjectionItem(
            key=key,
            value=value,
            evidence_ids=reference.evidence_ids,
            source_ids=reference.source_ids,
        )
        for key, value in values.items()
    )
    return SpecialistArtifactProjection(
        artifact_id=reference.artifact_id,
        artifact_type=reference.artifact_type,
        state_version=state.state_version,
        physical_event_id=state.physical_event.physical_event_id,
        items=items,
        admitted_evidence_ids=reference.evidence_ids,
        admitted_source_ids=reference.source_ids,
    )


def _expected_values(
    state: EvidenceWorldState,
    role: SpecialistRole,
    decision_support: DecisionSupportArtifact | None,
) -> dict[str, str]:
    if role is SpecialistRole.EVIDENCE_RECONCILIATION:
        result = {
            "event_identity": state.physical_event.physical_event_id,
            "evidence_gap_count": str(
                len(decision_support.evidence_gaps)
                if decision_support is not None
                else sum(
                    claim.availability is EvidenceAvailability.ABSENT
                    for claim in state.claims
                )
            ),
        }
        result.update(
            {
                f"claim:{claim.claim_key}:conflict": "retained"
                for claim in state.claims
                if any(
                    item.disposition is EvidenceDisposition.CONFLICTING
                    for item in claim.history
                )
            }
        )
        return result
    if role is SpecialistRole.DECISION_ANALYSIS and decision_support is not None:
        result = {
            "decision_policy": SAFETY_POLICY_FINGERPRINT,
            "scenario_mode": decision_support.scenario_analysis.mode.value,
            "recommendation_status": (
                decision_support.scenario_analysis.recommendation.status.value
            ),
        }
        result.update(
            {
                f"claim:{item.claim_key}:conflict": "retained"
                for item in decision_support.contradictions
            }
        )
        return result
    return {}


def _known_provenance(
    state: EvidenceWorldState,
    decision_support: DecisionSupportArtifact | None,
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
    return evidence_ids, source_ids


def _trusted_finding(
    draft: SpecialistFindingDraft, handoff: SpecialistHandoff
) -> SpecialistFinding:
    material = "|".join(
        (
            handoff.handoff_id,
            draft.specialist_role.value,
            draft.finding_key,
            draft.value,
            draft.state_version,
            *draft.evidence_ids,
            *draft.source_ids,
        )
    )
    return SpecialistFinding(
        finding_id=f"finding:model:{sha256(material.encode('utf-8')).hexdigest()[:24]}",
        specialist_role=draft.specialist_role,
        finding_key=draft.finding_key,
        value=draft.value,
        summary=draft.summary,
        state_version=draft.state_version,
        evidence_ids=draft.evidence_ids,
        source_ids=draft.source_ids,
        safety_policy_fingerprint=draft.safety_policy_fingerprint,
    )
