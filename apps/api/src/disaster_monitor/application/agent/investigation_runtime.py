"""Sequential runtime for the deliberately bounded Investigation Agent v1."""

from __future__ import annotations

from typing import TYPE_CHECKING

from disaster_monitor.application.agent.investigation_cases import (
    InvestigationCaseArtifact,
    InvestigationCaseCountry,
    InvestigationCaseStatus,
    InvestigationIncident,
    InvestigationTargetResult,
    assess_cross_hazard_pair,
    causation_requested,
    stable_case_id,
)
from disaster_monitor.application.agent.models import (
    AgentExecutionState,
    AgentStatus,
    InvestigationPlan,
    InvestigationTarget,
    PlanStatus,
    TaskKind,
    ValidatedDisasterTask,
)
from disaster_monitor.application.agent.planning import DEFAULT_TOOL_ORDER
from disaster_monitor.application.agent.tools import MAX_TOOL_CALLS
from disaster_monitor.application.agent.trace import ExecutionTrace, TraceEventKind
from disaster_monitor.application.services.investigation_report_renderer import (
    InvestigationReportRenderer,
)

if TYPE_CHECKING:
    from disaster_monitor.application.agent.runtime import DisasterAgentRuntime


class InvestigationRuntime:
    """Run exactly two application-built branches under one tool-call budget."""

    def __init__(self, runtime: DisasterAgentRuntime) -> None:
        self._runtime = runtime
        self._renderer = InvestigationReportRenderer()

    async def execute(
        self,
        task: ValidatedDisasterTask,
        *,
        conversation_id: str | None,
        model_call_count: int,
        model_events: list[tuple[TraceEventKind, str, bool]],
    ) -> AgentExecutionState:
        if len(task.investigation_targets) != 2 or task.country is None:
            raise ValueError(
                "Investigation Agent v1 requires two country-scoped targets."
            )
        parent = AgentExecutionState(
            task,
            InvestigationPlan(
                "investigation-case",
                task.question,
                (),
                status=PlanStatus.COMPLETED,
            ),
            conversation_id=conversation_id,
            model_call_count=model_call_count,
            trace=ExecutionTrace(),
        )
        self._runtime._record_task_and_models(parent, model_events)
        estimated_tool_calls = len(DEFAULT_TOOL_ORDER) * len(task.investigation_targets)
        if estimated_tool_calls > MAX_TOOL_CALLS:
            parent.final_status = AgentStatus.FAILED
            parent.capability_gaps.append(
                "The bounded two-hazard plan exceeds the request-wide tool-call budget."
            )
            self._terminate(parent, "tool_call_budget_exhausted")
            return parent

        used_tool_calls = 0
        results: list[InvestigationTargetResult] = []
        for target in task.investigation_targets:
            branch = await self._runtime.run_validated_task(
                _branch_task(task, target),
                conversation_id=conversation_id,
                initial_tool_call_count=used_tool_calls,
                allow_model_backed_specialists=False,
            )
            used_tool_calls = branch.tool_call_count
            results.append(_target_result(target, branch))
        parent.tool_call_count = used_tool_calls
        first, second = results
        assessment, correlations = assess_cross_hazard_pair(
            InvestigationIncident.from_target_result(first),
            InvestigationIncident.from_target_result(second),
            causation_requested=causation_requested(task.question),
        )
        partial = any(item.partial for item in results)
        case = InvestigationCaseArtifact(
            case_id=stable_case_id(task.country, task.investigation_targets),
            country=InvestigationCaseCountry.from_country(task.country),
            targets=(first, second),
            cross_hazard_assessment=assessment,
            correlations=correlations,
            status=(
                InvestigationCaseStatus.PARTIAL
                if partial
                else InvestigationCaseStatus.COMPLETED
            ),
            partial=partial,
        )
        parent.workspace.investigation_case = case
        parent.workspace.investigation_case_report = self._renderer.render(case)
        parent.workspace.source_ids.extend(
            source_id for result in results for source_id in result.source_ids
        )
        parent.warnings.extend(
            warning for result in results for warning in result.warnings
        )
        parent.capability_gaps.extend(
            gap for result in results for gap in result.capability_gaps
        )
        parent.final_status = AgentStatus.PARTIAL if partial else AgentStatus.COMPLETED
        self._terminate(
            parent,
            "investigation_case_partial" if partial else "investigation_case_completed",
        )
        return parent

    @staticmethod
    def _terminate(state: AgentExecutionState, reason: str) -> None:
        state.termination_reason = reason
        state.trace.record(TraceEventKind.TERMINATION, reason=reason)


def _branch_task(
    task: ValidatedDisasterTask, target: InvestigationTarget
) -> ValidatedDisasterTask:
    return ValidatedDisasterTask(
        question=task.question,
        kind=TaskKind.INVESTIGATION,
        requires_evidence=True,
        disaster=target.disaster,
        country=target.country,
        date_from=target.query.date_from,
        date_to=target.query.date_to,
        information_needs=target.information_needs,
        output_modalities=target.output_modalities,
        query=target.query,
        response_language=task.response_language,
        response_language_explicit=task.response_language_explicit,
    )


def _target_result(
    target: InvestigationTarget, state: AgentExecutionState
) -> InvestigationTargetResult:
    report = state.workspace.report
    sources = report.sources if report is not None else ()
    warnings = tuple(
        dict.fromkeys((*state.warnings, *(report.warnings if report else ())))
    )
    return InvestigationTargetResult(
        target=target,
        status=state.final_status,
        selected_event=report.selected_event if report is not None else None,
        sources=sources,
        warnings=warnings,
        sections=report.sections if report is not None else (),
        partial=(
            state.final_status is not AgentStatus.COMPLETED
            or report is None
            or report.partial
        ),
        termination_reason=state.termination_reason,
        physical_event_id=(
            state.workspace.selected_physical_event.physical_event_id
            if state.workspace.selected_physical_event is not None
            else None
        ),
        evidence_state_version=(
            state.workspace.evidence_state.state_version
            if state.workspace.evidence_state is not None
            else None
        ),
        source_ids=tuple(dict.fromkeys(state.workspace.source_ids)),
        capability_gaps=tuple(
            dict.fromkeys((*state.capability_gaps, *state.plan.capability_gaps))
        ),
    )
