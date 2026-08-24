import asyncio
import json
from dataclasses import replace
from datetime import UTC, datetime

import pytest

from disaster_monitor.application.disaster import DisasterQuery
from disaster_monitor.application.dto import ModelResponse
from disaster_monitor.application.ports.specialist_model import SpecialistModelRequest
from disaster_monitor.application.services.collaborative_investigation import (
    SAFETY_POLICY_FINGERPRINT,
)
from disaster_monitor.application.services.coordination_handoffs import (
    CoordinationHandoffPlanner,
)
from disaster_monitor.application.services.decision_support import (
    DecisionOptionGenerator,
)
from disaster_monitor.application.services.evidence_reconciliation import (
    EvidenceReconciler,
)
from disaster_monitor.application.services.hypothesis_reasoning import (
    HypothesisGenerator,
)
from disaster_monitor.application.services.incident_priority import (
    IncidentPriorityRanker,
)
from disaster_monitor.application.services.specialist_executor import (
    SpecialistExecutor,
)
from disaster_monitor.application.services.triage_autonomy import (
    TriageAutonomyPolicy,
)
from disaster_monitor.domain.coordination import (
    CoordinationPermission,
    SpecialistFindingDraft,
    SpecialistRole,
)
from disaster_monitor.domain.disaster import (
    CorrelationStatus,
    Country,
    Disaster,
    DisasterEvent,
    FactStatus,
    GeographicArea,
    ReportedFact,
    SituationReport,
    SourceReference,
)
from disaster_monitor.domain.memory import (
    MemoryAuthority,
    MemoryContextArtifact,
    MemoryContextItem,
    MemoryType,
)
from disaster_monitor.infrastructure.llm.structured_specialist_model import (
    StructuredSpecialistModel,
)

NOW = datetime(2026, 8, 24, 12, tzinfo=UTC)


class RecordingSpecialistModel:
    def __init__(self, drafts: tuple[SpecialistFindingDraft | Exception, ...]) -> None:
        self._drafts = list(drafts)
        self.requests: list[SpecialistModelRequest] = []
        self.active_calls = 0
        self.maximum_active_calls = 0

    async def generate_finding(
        self, request: SpecialistModelRequest
    ) -> SpecialistFindingDraft:
        self.requests.append(request)
        self.active_calls += 1
        self.maximum_active_calls = max(self.maximum_active_calls, self.active_calls)
        await asyncio.sleep(0)
        self.active_calls -= 1
        result = self._drafts.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


class JsonLanguageModel:
    def __init__(self, drafts: tuple[SpecialistFindingDraft, ...]) -> None:
        self.responses = [_draft_json(item) for item in drafts]
        self.requests = []
        self.active_calls = 0
        self.maximum_active_calls = 0

    async def generate(self, request):
        self.requests.append(request)
        self.active_calls += 1
        self.maximum_active_calls = max(self.maximum_active_calls, self.active_calls)
        await asyncio.sleep(0)
        self.active_calls -= 1
        return ModelResponse(self.responses.pop(0), "shared-local-model")

    async def check_readiness(self):
        raise AssertionError("Specialist execution does not perform readiness I/O.")


class RawLanguageModel:
    def __init__(self, text: str) -> None:
        self.text = text

    async def generate(self, request):
        return ModelResponse(self.text, "shared-local-model")

    async def check_readiness(self):
        raise AssertionError("Specialist execution does not perform readiness I/O.")


def _products():
    country = Country("TST", "Testland", (), GeographicArea(0, 10, 0, 10), "UTC")
    source = SourceReference(
        "test-source",
        "Test authority",
        "Test event",
        "https://example.test/event",
        NOW,
        NOW,
        NOW,
    )
    event = DisasterEvent(
        "test:event-1", Disaster.FLOOD, "Testland", country, NOW, source
    )
    query = DisasterQuery(Disaster.FLOOD, country, "recent", ("latest",))
    packet = EvidenceReconciler().build(query, event, (), warnings=(), retrieved_at=NOW)
    state = packet.world_state
    assert state is not None
    hypotheses = HypothesisGenerator().generate(state)
    priority = IncidentPriorityRanker().assess(state)
    triage = TriageAutonomyPolicy().decide(priority)
    decision = DecisionOptionGenerator().generate(state, hypotheses, priority, triage)
    planner = CoordinationHandoffPlanner()
    handoffs = (
        planner.for_evidence_state(state),
        planner.for_decision_support(decision),
    )
    return state, decision, handoffs


def _products_with_current_fact():
    country = Country("TST", "Testland", (), GeographicArea(0, 10, 0, 10), "UTC")
    event_source = SourceReference(
        "test-event-source",
        "Test event authority",
        "Test event",
        "https://example.test/event",
        NOW,
        NOW,
        NOW,
    )
    report_source = SourceReference(
        "test-report-source",
        "Test report authority",
        "Test report",
        "https://example.test/report",
        NOW,
        NOW,
        NOW,
    )
    event = DisasterEvent(
        "test:event-1", Disaster.FLOOD, "Testland", country, NOW, event_source
    )
    report = SituationReport(
        source=report_source,
        narrative="A source-backed impact update for the selected flood event.",
        facts=(
            ReportedFact(
                "impact",
                "Affected people",
                "10",
                FactStatus.CONFIRMED,
                report_source,
                event_id=event.event_id,
                observed_at=NOW,
            ),
        ),
        event_id=event.event_id,
        correlation=CorrelationStatus.MATCHED,
        reported_event_time=NOW,
        countries=(country.canonical_name,),
        country_codes=(country.alpha3_code,),
        disaster=Disaster.FLOOD,
    )
    query = DisasterQuery(Disaster.FLOOD, country, "recent", ("latest",))
    packet = EvidenceReconciler().build(
        query, event, (report,), warnings=(), retrieved_at=NOW
    )
    state = packet.world_state
    assert state is not None
    hypotheses = HypothesisGenerator().generate(state)
    priority = IncidentPriorityRanker().assess(state)
    triage = TriageAutonomyPolicy().decide(priority)
    decision = DecisionOptionGenerator().generate(state, hypotheses, priority, triage)
    planner = CoordinationHandoffPlanner()
    handoffs = (
        planner.for_evidence_state(state),
        planner.for_decision_support(decision),
    )
    return state, decision, handoffs


def _drafts(state, decision, handoffs):
    evidence, decision_handoff = handoffs
    decision_evidence_ids = tuple(
        dict.fromkeys(
            evidence_id for fact in decision.facts for evidence_id in fact.evidence_ids
        )
    )
    decision_source_ids = tuple(
        dict.fromkeys(
            source_id for fact in decision.facts for source_id in fact.source_ids
        )
    )
    return (
        SpecialistFindingDraft(
            specialist_role=SpecialistRole.EVIDENCE_RECONCILIATION,
            task_type=evidence.task_type,
            finding_key="event_identity",
            value=state.physical_event.physical_event_id,
            summary="The admitted physical-event identity remains unchanged.",
            state_version=state.state_version,
            evidence_ids=(state.physical_event.physical_event_id,),
            source_ids=(state.physical_event.event.source.source_id,),
            permissions=evidence.granted_permissions,
            safety_policy_fingerprint=SAFETY_POLICY_FINGERPRINT,
        ),
        SpecialistFindingDraft(
            specialist_role=SpecialistRole.DECISION_ANALYSIS,
            task_type=decision_handoff.task_type,
            finding_key="recommendation_status",
            value=decision.scenario_analysis.recommendation.status.value,
            summary="The bounded recommendation authority state remains unchanged.",
            state_version=state.state_version,
            evidence_ids=decision_evidence_ids,
            source_ids=decision_source_ids,
            permissions=decision_handoff.granted_permissions,
            safety_policy_fingerprint=SAFETY_POLICY_FINGERPRINT,
        ),
    )


def _draft_json(draft: SpecialistFindingDraft) -> str:
    return json.dumps(
        {
            "specialist_role": draft.specialist_role.value,
            "task_type": draft.task_type.value,
            "finding_key": draft.finding_key,
            "value": draft.value,
            "summary": draft.summary,
            "state_version": draft.state_version,
            "evidence_ids": list(draft.evidence_ids),
            "source_ids": list(draft.source_ids),
            "permissions": [item.value for item in draft.permissions],
            "safety_policy_fingerprint": draft.safety_policy_fingerprint,
        }
    )


@pytest.mark.asyncio
async def test_two_specialists_share_one_model_and_execute_sequentially() -> None:
    state, decision, handoffs = _products()
    model = RecordingSpecialistModel(_drafts(state, decision, handoffs))

    result = await SpecialistExecutor(model, max_model_calls=2).execute(
        state,
        handoffs,
        decision_support=decision,
    )

    assert result.model_call_count == 2
    assert result.fallback_reason is None
    assert len(result.findings) == 2
    assert model.maximum_active_calls == 1
    assert [request.handoff.receiver_role for request in model.requests] == [
        SpecialistRole.EVIDENCE_RECONCILIATION,
        SpecialistRole.DECISION_ANALYSIS,
    ]
    assert all(request.tools == () for request in model.requests)
    assert all(request.provider_authority is False for request in model.requests)
    assert all(request.recursive_agent_authority is False for request in model.requests)


@pytest.mark.asyncio
async def test_repeated_execution_cannot_reset_request_wide_specialist_budget() -> None:
    state, decision, handoffs = _products()
    drafts = _drafts(state, decision, handoffs)
    model = RecordingSpecialistModel((*drafts, *drafts))
    executor = SpecialistExecutor(model, max_model_calls=2)

    first = await executor.execute(
        state,
        handoffs,
        decision_support=decision,
        request_model_calls=0,
    )
    canonical_version = state.state_version
    second = await executor.execute(
        state,
        handoffs,
        decision_support=decision,
        request_model_calls=first.model_call_count,
    )

    assert first.model_call_count == 2
    assert second.model_call_count == 0
    assert second.findings == ()
    assert second.fallback_reason == "specialist_model_call_budget_exceeded"
    assert len(model.requests) == 2
    assert state.state_version == canonical_version


@pytest.mark.asyncio
@pytest.mark.parametrize("mutation", ("different_item", "missing", "extra"))
async def test_finding_provenance_must_exactly_match_the_selected_item(
    mutation: str,
) -> None:
    state, decision, handoffs = _products_with_current_fact()
    handoff = handoffs[0]

    class ItemProvenanceModel:
        async def generate_finding(self, request):
            selected = next(
                item for item in request.artifact.items if item.key == "event_identity"
            )
            other = next(
                item
                for item in request.artifact.items
                if item.key == "evidence_gap_count"
            )
            if mutation == "different_item":
                evidence_ids = other.evidence_ids
                source_ids = other.source_ids
            elif mutation == "missing":
                evidence_ids = other.evidence_ids[:-1]
                source_ids = other.source_ids[:-1]
                selected = other
            else:
                evidence_ids = tuple(
                    dict.fromkeys((*selected.evidence_ids, *other.evidence_ids))
                )
                source_ids = tuple(
                    dict.fromkeys((*selected.source_ids, *other.source_ids))
                )
            return SpecialistFindingDraft(
                specialist_role=handoff.receiver_role,
                task_type=handoff.task_type,
                finding_key=selected.key,
                value=selected.value,
                summary="The selected canonical value remains unchanged.",
                state_version=state.state_version,
                evidence_ids=evidence_ids,
                source_ids=source_ids,
                permissions=handoff.granted_permissions,
                safety_policy_fingerprint=SAFETY_POLICY_FINGERPRINT,
            )

    result = await SpecialistExecutor(ItemProvenanceModel()).execute(
        state, (handoff,), decision_support=decision
    )

    assert result.findings == ()
    assert result.fallback_reason in {
        "evidence_membership_violation",
        "source_membership_violation",
    }
    assert result.provenance_validation_failures == 1


@pytest.mark.asyncio
async def test_valid_item_bound_specialist_output_is_accepted() -> None:
    state, decision, handoffs = _products_with_current_fact()
    handoff = handoffs[0]

    class ItemBoundModel:
        async def generate_finding(self, request):
            item = next(
                value
                for value in request.artifact.items
                if value.key == "event_identity"
            )
            return SpecialistFindingDraft(
                specialist_role=handoff.receiver_role,
                task_type=handoff.task_type,
                finding_key=item.key,
                value=item.value,
                summary="The selected canonical value remains unchanged.",
                state_version=state.state_version,
                evidence_ids=item.evidence_ids,
                source_ids=item.source_ids,
                permissions=handoff.granted_permissions,
                safety_policy_fingerprint=SAFETY_POLICY_FINGERPRINT,
            )

    result = await SpecialistExecutor(ItemBoundModel()).execute(
        state, (handoff,), decision_support=decision
    )

    assert len(result.findings) == 1
    assert result.fallback_reason is None


@pytest.mark.asyncio
async def test_historical_memory_identifiers_cannot_satisfy_current_provenance() -> (
    None
):
    state, decision, handoffs = _products_with_current_fact()
    handoff = handoffs[0]
    memory_id = "memory:historical-only"
    context = MemoryContextArtifact(
        context_id="memory-context:test",
        conversation_id="conversation-a",
        physical_event_id=state.physical_event.physical_event_id,
        records=(
            MemoryContextItem(
                memory_id=memory_id,
                memory_type=MemoryType.PHYSICAL_EVENT_REFERENCE,
                summary="Historical reference only.",
                conversation_id="conversation-a",
                physical_event_id=state.physical_event.physical_event_id,
                disaster_identifier="flood",
                country_code="TST",
                source_message_ids=("message:historical",),
                evidence_ids=(state.physical_event.physical_event_id,),
                world_state_version="state:historical",
                confirmed_at=NOW,
                authority=MemoryAuthority.HISTORICAL_CONTEXT,
                may_satisfy_current_evidence=False,
            ),
        ),
        created_at=NOW,
        total_characters=26,
        maximum_records=5,
        maximum_characters=1_500,
    )

    class MemoryProvenanceModel:
        async def generate_finding(self, request):
            item = next(
                value
                for value in request.artifact.items
                if value.key == "event_identity"
            )
            return SpecialistFindingDraft(
                specialist_role=handoff.receiver_role,
                task_type=handoff.task_type,
                finding_key=item.key,
                value=item.value,
                summary="Historical memory must not become current evidence.",
                state_version=state.state_version,
                evidence_ids=(memory_id,),
                source_ids=item.source_ids,
                permissions=handoff.granted_permissions,
                safety_policy_fingerprint=SAFETY_POLICY_FINGERPRINT,
            )

    result = await SpecialistExecutor(MemoryProvenanceModel()).execute(
        state,
        (handoff,),
        decision_support=decision,
        memory_context=context,
    )

    assert result.findings == ()
    assert result.fallback_reason == "evidence_membership_violation"


@pytest.mark.asyncio
async def test_structured_specialists_reuse_one_language_model_without_tools() -> None:
    state, decision, handoffs = _products()
    language_model = JsonLanguageModel(_drafts(state, decision, handoffs))

    result = await SpecialistExecutor(
        StructuredSpecialistModel(language_model), max_model_calls=2
    ).execute(state, handoffs, decision_support=decision)

    assert result.fallback_reason is None
    assert result.model_call_count == 2
    assert len(language_model.requests) == 2
    assert language_model.maximum_active_calls == 1
    assert all(request.tools == () for request in language_model.requests)


@pytest.mark.asyncio
async def test_malformed_structured_model_output_falls_back_without_repair_call() -> (
    None
):
    state, decision, handoffs = _products()

    result = await SpecialistExecutor(
        StructuredSpecialistModel(RawLanguageModel("{}")), max_model_calls=2
    ).execute(state, handoffs, decision_support=decision)

    assert result.findings == ()
    assert result.model_call_count == 1
    assert result.fallback_reason == "specialist_model_failure"


@pytest.mark.asyncio
async def test_specialist_receives_only_supervisor_built_read_only_memory() -> None:
    state, decision, handoffs = _products()
    context = MemoryContextArtifact(
        context_id="memory-context:test",
        conversation_id="conversation-a",
        physical_event_id=state.physical_event.physical_event_id,
        records=(),
        created_at=NOW,
        total_characters=0,
        maximum_records=5,
        maximum_characters=1_500,
    )
    model = RecordingSpecialistModel((_drafts(state, decision, handoffs)[0],))

    result = await SpecialistExecutor(model, max_model_calls=2).execute(
        state,
        handoffs[:1],
        decision_support=decision,
        memory_context=context,
    )

    assert result.fallback_reason is None
    assert model.requests[0].memory_context is context
    assert not hasattr(model.requests[0], "memory_store")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("mutation", "expected_reason"),
    [
        ("state", "state_version_lineage_violation"),
        ("evidence", "evidence_membership_violation"),
        ("permissions", "permission_escalation"),
        ("policy", "safety_policy_violation"),
        ("contradiction", "contradictory_specialist_output"),
    ],
)
async def test_invalid_or_privilege_escalating_draft_fails_closed(
    mutation: str, expected_reason: str
) -> None:
    state, decision, handoffs = _products()
    drafts = list(_drafts(state, decision, handoffs))
    draft = drafts[0]
    if mutation == "state":
        draft = replace(draft, state_version="state:invented")
    elif mutation == "evidence":
        draft = replace(draft, evidence_ids=("evidence:invented",))
    elif mutation == "permissions":
        draft = replace(
            draft,
            permissions=(
                *draft.permissions,
                CoordinationPermission.EXECUTE_PROVIDER_IO,
            ),
        )
    elif mutation == "policy":
        draft = replace(draft, safety_policy_fingerprint="policy:changed")
    else:
        draft = replace(draft, value="physical-event:contradiction")
    drafts[0] = draft
    model = RecordingSpecialistModel(tuple(drafts))

    result = await SpecialistExecutor(model, max_model_calls=2).execute(
        state,
        handoffs,
        decision_support=decision,
    )

    assert result.findings == ()
    assert result.fallback_reason == expected_reason
    assert result.model_call_count == 1


@pytest.mark.asyncio
async def test_model_failure_and_call_budget_preserve_deterministic_fallback() -> None:
    state, decision, handoffs = _products()
    valid = _drafts(state, decision, handoffs)
    failed = await SpecialistExecutor(
        RecordingSpecialistModel((RuntimeError("model unavailable"),)),
        max_model_calls=2,
    ).execute(state, handoffs, decision_support=decision)
    over_budget = await SpecialistExecutor(
        RecordingSpecialistModel(valid), max_model_calls=1
    ).execute(state, handoffs, decision_support=decision)
    disabled = await SpecialistExecutor(None, max_model_calls=2).execute(
        state, handoffs, decision_support=decision
    )

    assert failed.findings == ()
    assert failed.fallback_reason == "specialist_model_failure"
    assert failed.model_call_count == 1
    assert over_budget.findings == ()
    assert over_budget.fallback_reason == "specialist_model_call_budget_exceeded"
    assert over_budget.model_call_count == 0
    assert disabled.findings == ()
    assert disabled.fallback_reason is None
    assert disabled.model_call_count == 0
