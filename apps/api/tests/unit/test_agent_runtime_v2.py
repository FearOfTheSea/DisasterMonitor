from dataclasses import dataclass, field
from datetime import UTC, datetime

import pytest

from disaster_monitor.application.agent.models import (
    AgentExecutionState,
    AgentReview,
    DisasterTaskDraft,
    InvestigationPlan,
    ReviewDecision,
    TaskKind,
)
from disaster_monitor.application.agent.planning import default_investigation_plan
from disaster_monitor.application.agent.runtime import DisasterAgentRuntime
from disaster_monitor.application.agent.sufficiency import (
    EvidenceSufficiencyState,
)
from disaster_monitor.application.agent.tooling import ToolDescription, ToolRegistry
from disaster_monitor.application.agent.trace import (
    TraceEvent,
    TraceEventKind,
    TraceValidationError,
    replay_trace,
)
from disaster_monitor.application.disaster import (
    DisasterQuery,
    EvidencePacket,
    GeographicScope,
    ProviderBatch,
    ProviderIssue,
)
from disaster_monitor.application.services.disaster_query_parser import (
    DisasterQueryParser,
)
from disaster_monitor.domain.disaster import (
    Disaster,
    DisasterEvent,
    SourceReference,
)
from disaster_monitor.infrastructure.geography.static_country_catalog import (
    StaticCountryCatalog,
)

NOW = datetime(2026, 8, 5, 12, tzinfo=UTC)


def _event() -> DisasterEvent:
    country = StaticCountryCatalog().get_by_alpha3("JPN")
    assert country is not None
    source = SourceReference(
        "fixture-event-source",
        "Fixture authority",
        "Fixture event",
        "https://example.test/event",
        NOW,
        NOW,
        NOW,
    )
    return DisasterEvent(
        "fixture:event",
        Disaster.EARTHQUAKE,
        "Fixture location",
        country,
        NOW,
        source,
    )


def _packet(
    query: DisasterQuery, event: DisasterEvent, *, complete: bool
) -> EvidencePacket:
    return EvidencePacket(
        query=query,
        event=event,
        facts=(),
        narratives=(),
        sources=(event.source,),
        conflicts=(),
        warnings=(),
        retrieved_at=NOW,
        stale=False,
        completeness=(
            "event_verified_with_event_specific_evidence"
            if complete
            else "event_verified_no_situation_evidence"
        ),
        partial=not complete,
    )


@dataclass
class Workflow:
    event_batches: list[ProviderBatch[DisasterEvent]]
    situation_batches: list[ProviderBatch[object]]
    event: DisasterEvent
    executions: list[str] = field(default_factory=list)
    compose_calls: int = 0

    def tools(self) -> ToolRegistry:
        return ToolRegistry(
            tuple(
                _WorkflowTool(name, self)
                for name in (
                    "list_sources_for_task",
                    "find_disaster_event",
                    "retrieve_situation_evidence",
                    "reconcile_disaster_evidence",
                    "compose_disaster_answer",
                )
            )
        )


class _WorkflowTool:
    def __init__(self, name: str, workflow: Workflow) -> None:
        self.workflow = workflow
        self.description = ToolDescription(name, name, (), (), (), (), False)

    async def execute(self, state: AgentExecutionState) -> str:
        self.workflow.executions.append(self.description.name)
        if self.description.name == "find_disaster_event":
            batch = self.workflow.event_batches.pop(0)
            state.workspace.event_batch = batch
            if batch.records:
                state.workspace.selected_event = batch.records[0]
        elif self.description.name == "retrieve_situation_evidence":
            state.workspace.situation_batch = self.workflow.situation_batches.pop(0)
        elif self.description.name == "reconcile_disaster_evidence":
            batch = state.workspace.situation_batch
            assert batch is not None
            query = state.task.query
            event = state.workspace.selected_event
            assert query is not None and event is not None
            state.workspace.evidence_packet = _packet(
                query, event, complete=bool(batch.records)
            )
        elif self.description.name == "compose_disaster_answer":
            self.workflow.compose_calls += 1
            state.workspace.report = type(
                "Report",
                (),
                {
                    "response_type": "current_disaster",
                    "partial": state.workspace.evidence_packet is None
                    or state.workspace.evidence_packet.partial,
                },
            )()
        return self.description.name


class _ReviewAgent:
    def __init__(self, selection: str | None = None) -> None:
        self.selection = selection
        self.assessments = []

    async def interpret(self, question: str) -> DisasterTaskDraft:
        return DisasterTaskDraft(
            disaster_related=True,
            current_or_event_specific=True,
            task_kind=TaskKind.INVESTIGATION,
            disaster=Disaster.EARTHQUAKE,
            country_code="JPN",
            country_name="Japan",
            geographic_scope=GeographicScope.COUNTRY,
            information_needs=("event_overview",),
            output_modalities=("text",),
            canonical=True,
        )

    async def propose_plan(
        self, task, tool_descriptions: tuple[str, ...]
    ) -> InvestigationPlan:
        return default_investigation_plan(task)

    async def review_progress(self, task, assessment):
        self.assessments.append(assessment)
        return AgentReview(
            ReviewDecision.REPLAN
            if self.selection is not None
            else ReviewDecision.FINISH,
            "bounded review",
            self.selection,
        )


def _runtime(workflow: Workflow, agent=None) -> DisasterAgentRuntime:
    catalog = StaticCountryCatalog()
    return DisasterAgentRuntime(
        country_catalog=catalog,
        query_parser=DisasterQueryParser(catalog),
        tool_registry=workflow.tools(),
        agent_model=agent,
    )


def _retryable_issue() -> ProviderIssue:
    return ProviderIssue(
        "fixture",
        "fixture provider temporarily unavailable",
        reason_code="timeout",
        retryable=True,
    )


@pytest.mark.asyncio
async def test_complete_evidence_is_sufficient_and_composes_once() -> None:
    event = _event()
    workflow = Workflow(
        [ProviderBatch((event,))],
        [ProviderBatch((object(),))],
        event,
    )

    state = await _runtime(workflow).run("Latest earthquake information in Japan.")

    assert state.sufficiency_assessment is not None
    assert state.sufficiency_assessment.state is EvidenceSufficiencyState.SUFFICIENT
    assert state.sufficiency_assessment.follow_up_options == ()
    assert state.replan_count == 0
    assert workflow.compose_calls == 1
    assert replay_trace(state.trace).composition_count == 1


@pytest.mark.asyncio
async def test_retryable_situation_failure_allows_one_selected_followup() -> None:
    event = _event()
    agent = _ReviewAgent("retry_situation_evidence")
    workflow = Workflow(
        [ProviderBatch((event,))],
        [ProviderBatch(issues=(_retryable_issue(),)), ProviderBatch((object(),))],
        event,
    )

    state = await _runtime(workflow, agent).run(
        "Latest earthquake information in Japan."
    )

    assert agent.assessments[0].option_ids == ("retry_situation_evidence",)
    assert workflow.executions.count("retrieve_situation_evidence") == 2
    assert workflow.executions.count("reconcile_disaster_evidence") == 2
    assert state.replan_count == 1
    assert state.tool_call_count == 7
    assert state.model_call_count == 3
    assert len(agent.assessments) == 1
    assert state.sufficiency_assessment is not None
    assert state.sufficiency_assessment.state is EvidenceSufficiencyState.SUFFICIENT
    assert workflow.compose_calls == 1
    assert replay_trace(state.trace).replan_count == 1


@pytest.mark.asyncio
async def test_retryable_event_failure_uses_bounded_dependent_recovery_path() -> None:
    event = _event()
    agent = _ReviewAgent("retry_event_discovery")
    workflow = Workflow(
        [ProviderBatch(issues=(_retryable_issue(),)), ProviderBatch((event,))],
        [ProviderBatch((object(),))],
        event,
    )

    state = await _runtime(workflow, agent).run(
        "Latest earthquake information in Japan."
    )

    assert workflow.executions.count("find_disaster_event") == 2
    assert workflow.executions.count("retrieve_situation_evidence") == 1
    assert workflow.executions.count("reconcile_disaster_evidence") == 1
    assert state.replan_count == 1
    assert state.tool_call_count == 8
    assert workflow.compose_calls == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "batch",
    (
        ProviderBatch(),
        ProviderBatch(issues=(ProviderIssue("fixture", "bad", retryable=False),)),
    ),
)
async def test_successful_empty_and_non_retryable_event_failures_do_not_retry(
    batch,
) -> None:
    event = _event()
    agent = _ReviewAgent("retry_event_discovery")
    workflow = Workflow([batch], [], event)

    state = await _runtime(workflow, agent).run(
        "Latest earthquake information in Japan."
    )

    assert state.replan_count == 0
    assert workflow.executions.count("find_disaster_event") == 1
    assert workflow.compose_calls == 1
    assert state.sufficiency_assessment is not None
    assert state.sufficiency_assessment.state is EvidenceSufficiencyState.TERMINAL_GAP
    assert "retry_event_discovery" not in state.sufficiency_assessment.option_ids


@pytest.mark.asyncio
async def test_unknown_followup_option_is_rejected_without_provider_call() -> None:
    event = _event()
    agent = _ReviewAgent("invented_provider_retry")
    workflow = Workflow(
        [ProviderBatch((event,))],
        [ProviderBatch(issues=(_retryable_issue(),))],
        event,
    )

    state = await _runtime(workflow, agent).run(
        "Latest earthquake information in Japan."
    )

    assert state.replan_count == 0
    assert workflow.executions.count("retrieve_situation_evidence") == 1
    assert workflow.compose_calls == 1
    assert any("no permitted follow-up" in item for item in state.warnings)


@pytest.mark.asyncio
async def test_failed_retry_retains_first_pass_evidence_and_cannot_retry_again() -> (
    None
):
    event = _event()
    agent = _ReviewAgent("retry_situation_evidence")
    workflow = Workflow(
        [ProviderBatch((event,))],
        [
            ProviderBatch((object(),), (_retryable_issue(),)),
            ProviderBatch(issues=(_retryable_issue(),)),
        ],
        event,
    )

    state = await _runtime(workflow, agent).run(
        "Latest earthquake information in Japan."
    )

    assert state.replan_count == 1
    assert state.workspace.evidence_packet is not None
    assert state.workspace.evidence_packet.completeness == (
        "event_verified_with_event_specific_evidence"
    )
    assert state.workspace.evidence_packet.partial is False
    assert workflow.compose_calls == 1
    assert len(agent.assessments) == 1


@pytest.mark.asyncio
async def test_no_model_does_not_turn_a_retryable_gap_into_an_extra_live_call() -> None:
    event = _event()
    workflow = Workflow(
        [ProviderBatch((event,))],
        [ProviderBatch(issues=(_retryable_issue(),))],
        event,
    )

    state = await _runtime(workflow).run("Latest earthquake information in Japan.")

    assert state.model_call_count == 0
    assert state.replan_count == 0
    assert workflow.executions.count("retrieve_situation_evidence") == 1
    assert workflow.compose_calls == 1


def test_trace_replay_rejects_impossible_ordering_and_multiple_replans() -> None:
    def event(sequence: int, kind: TraceEventKind, **attributes: str) -> TraceEvent:
        return TraceEvent(sequence, kind, tuple(sorted(attributes.items())))

    before_evidence = (
        event(1, TraceEventKind.TASK_VALIDATED),
        event(2, TraceEventKind.INITIAL_PLAN_VALIDATED),
        event(3, TraceEventKind.COMPOSITION),
        event(4, TraceEventKind.TERMINATION, reason="bad"),
    )
    with pytest.raises(TraceValidationError, match="Composition"):
        replay_trace(before_evidence)

    multiple = (
        event(1, TraceEventKind.TASK_VALIDATED),
        event(2, TraceEventKind.INITIAL_PLAN_VALIDATED),
        event(3, TraceEventKind.SUFFICIENCY_ASSESSED, phase="initial"),
        event(4, TraceEventKind.REVIEW_DECISION, decision="replan"),
        event(5, TraceEventKind.FOLLOWUP_SELECTED, option_id="one"),
        event(6, TraceEventKind.FOLLOWUP_PLAN_VALIDATED),
        event(7, TraceEventKind.FOLLOWUP_EXECUTED, result="completed"),
        event(8, TraceEventKind.SUFFICIENCY_ASSESSED, phase="followup"),
        event(9, TraceEventKind.FOLLOWUP_SELECTED, option_id="two"),
    )
    with pytest.raises(TraceValidationError):
        replay_trace(multiple)


@pytest.mark.asyncio
async def test_trace_is_deterministic_and_valid_runs_replay() -> None:
    event = _event()

    def workflow() -> Workflow:
        return Workflow([ProviderBatch((event,))], [ProviderBatch((object(),))], event)

    first = await _runtime(workflow()).run("Latest earthquake information in Japan.")
    second = await _runtime(workflow()).run("Latest earthquake information in Japan.")

    assert first.trace.events == second.trace.events
    replayed = replay_trace(first.trace)
    assert replayed.terminated is True
    assert replayed.composition_count == 1
