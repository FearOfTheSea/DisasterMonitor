"""Small request-scoped disaster-agent runtime with explicit budgets."""

from disaster_monitor.application.agent.models import (
    AgentExecutionState,
    AgentStatus,
    InvestigationAction,
    InvestigationPlan,
    PlanStatus,
    ReviewDecision,
    TaskKind,
    ValidationStatus,
)
from disaster_monitor.application.agent.planning import (
    default_investigation_plan,
    validate_plan,
)
from disaster_monitor.application.agent.task_normalization import (
    deterministic_task_draft,
    validate_disaster_task,
)
from disaster_monitor.application.agent.tooling import ToolRegistry, execute_plan
from disaster_monitor.application.disaster import GeographicScope
from disaster_monitor.application.ports.agent_model import AgentModel
from disaster_monitor.application.ports.geography import CountryCatalog
from disaster_monitor.application.services.disaster_query_parser import (
    DisasterQueryParser,
)
from disaster_monitor.application.services.worldwide_disaster import (
    WorldwideDisasterReportService,
)
from disaster_monitor.application.services.worldwide_disaster_policy import (
    WorldwideDisasterPolicyRegistry,
    default_worldwide_disaster_policy_registry,
)
from disaster_monitor.domain.multimodal import MultimodalAsset

MAX_MODEL_CALLS = 4
MAX_REPLANS = 1


class DisasterAgentRuntime:
    def __init__(
        self,
        *,
        country_catalog: CountryCatalog,
        query_parser: DisasterQueryParser,
        tool_registry: ToolRegistry,
        agent_model: AgentModel | None = None,
        worldwide_report: WorldwideDisasterReportService | None = None,
        worldwide_policies: WorldwideDisasterPolicyRegistry | None = None,
    ) -> None:
        self._country_catalog = country_catalog
        self._query_parser = query_parser
        self._tools = tool_registry
        self._agent_model = agent_model
        self._worldwide_report = worldwide_report
        self._worldwide_policies = (
            worldwide_policies or default_worldwide_disaster_policy_registry()
        )

    async def run(
        self, question: str, *, multimodal_assets: tuple[MultimodalAsset, ...] = ()
    ) -> AgentExecutionState:
        model_calls = 0
        draft = deterministic_task_draft(question)
        task = validate_disaster_task(
            question,
            draft,
            country_catalog=self._country_catalog,
            query_parser=self._query_parser,
            worldwide_policies=self._worldwide_policies,
        )
        empty_plan = InvestigationPlan(
            "no-plan", task.question, (), status=PlanStatus.COMPLETED
        )
        if task.kind in {TaskKind.NON_DISASTER, TaskKind.GENERAL_KNOWLEDGE}:
            state = AgentExecutionState(task, empty_plan, model_call_count=model_calls)
            state.final_status = AgentStatus.DELEGATED
            state.termination_reason = task.kind.value
            return state
        if task.validation_status != ValidationStatus.VALID:
            state = AgentExecutionState(task, empty_plan, model_call_count=model_calls)
            state.final_status = AgentStatus.CLARIFICATION_REQUIRED
            if task.validation_status == ValidationStatus.CATALOG_LIMITATION:
                state.final_status = AgentStatus.COVERAGE_UNAVAILABLE
            state.termination_reason = task.validation_status.value
            state.capability_gaps.append(
                task.detail or "Task validation is incomplete."
            )
            return state

        if task.geographic_scope is GeographicScope.WORLDWIDE:
            state = AgentExecutionState(task, empty_plan, model_call_count=model_calls)
            if self._worldwide_report is None or task.worldwide_query is None:
                state.final_status = AgentStatus.COVERAGE_UNAVAILABLE
                state.termination_reason = "coverage_unavailable"
                state.capability_gaps.append(
                    "No worldwide event-reporting capability is configured."
                )
                return state
            try:
                state.workspace.report = await self._worldwide_report.execute(
                    task.worldwide_query
                )
            except Exception:
                state.final_status = AgentStatus.FAILED
                state.termination_reason = "worldwide_execution_failed"
                state.warnings.append(
                    "The bounded worldwide investigation stopped safely."
                )
                return state
            state.actions.append(
                InvestigationAction(
                    "worldwide-event-discovery",
                    "Queried the registry-approved worldwide event source.",
                )
            )
            state.capability_gaps.append(
                "Worldwide casualty, damage, warning, and response coverage is not "
                "complete."
            )
            if state.workspace.report.selected_event is not None:
                state.actions.append(
                    InvestigationAction(
                        "worldwide-event-selection",
                        "Selected and rendered one source-backed worldwide event.",
                    )
                )
            state.workspace.source_ids.extend(
                source.source_id for source in state.workspace.report.sources
            )
            if state.workspace.report.selected_event is None:
                state.final_status = AgentStatus.COVERAGE_UNAVAILABLE
                state.termination_reason = "coverage_unavailable"
            else:
                state.final_status = AgentStatus.PARTIAL
                state.termination_reason = "partial_global_event_evidence"
            state.warnings.extend(state.workspace.report.warnings)
            return state

        plan = default_investigation_plan(
            task, multimodal_assets_available=bool(multimodal_assets)
        )
        if self._agent_model is not None and model_calls < MAX_MODEL_CALLS:
            try:
                proposed = await self._agent_model.propose_plan(
                    task,
                    tuple(item.planning_text() for item in self._tools.descriptions),
                )
                model_calls += 1
                plan = validate_plan(
                    proposed,
                    allowed_tools=self._tools.names,
                    requires_multimodal=bool(multimodal_assets),
                )
            except Exception:
                model_calls += 1
                plan = default_investigation_plan(
                    task, multimodal_assets_available=bool(multimodal_assets)
                )
        state = AgentExecutionState(task, plan, model_call_count=model_calls)
        state.workspace.multimodal_assets = multimodal_assets
        state.capability_gaps.extend(plan.capability_gaps)
        try:
            await execute_plan(state, self._tools)
        except Exception as error:
            state.final_status = AgentStatus.FAILED
            state.termination_reason = _safe_termination(error)
            state.warnings.append("The bounded investigation stopped safely.")
            return state

        if self._agent_model is not None and state.model_call_count < MAX_MODEL_CALLS:
            try:
                review = await self._agent_model.review_progress(
                    task, tuple(state.completed_steps)
                )
                state.model_call_count += 1
                if review.decision == ReviewDecision.CLARIFY:
                    state.warnings.append(
                        "The investigation review identified ambiguity."
                    )
                elif review.decision == ReviewDecision.REPLAN:
                    state.replan_count = min(state.replan_count + 1, MAX_REPLANS)
                    state.warnings.append(
                        "No distinct allowlisted alternative path was available "
                        "for replanning."
                    )
            except Exception:
                state.model_call_count += 1
        report = state.workspace.report
        if report is None:
            state.final_status = AgentStatus.FAILED
            state.termination_reason = "no_grounded_response"
        elif report.response_type.endswith("coverage_unavailable"):
            state.final_status = AgentStatus.COVERAGE_UNAVAILABLE
            state.termination_reason = "coverage_unavailable"
        elif report.partial:
            state.final_status = AgentStatus.PARTIAL
            state.termination_reason = "partial_evidence"
        else:
            state.final_status = AgentStatus.COMPLETED
            state.termination_reason = "grounded_answer_composed"
        return state


def _safe_termination(error: Exception) -> str:
    text = str(error).lower()
    if "budget" in text:
        return "tool_call_budget_exhausted"
    if "prerequisite" in text or "sequencing" in text:
        return "invalid_tool_sequencing"
    if "unknown agent tool" in text:
        return "unknown_tool"
    return "tool_execution_failed"
