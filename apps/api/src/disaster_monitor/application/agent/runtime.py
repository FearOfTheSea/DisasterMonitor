"""Small request-scoped disaster-agent runtime with explicit budgets."""

from disaster_monitor.application.agent.models import (
    AgentExecutionState,
    AgentStatus,
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
from disaster_monitor.application.ports.agent_model import AgentModel
from disaster_monitor.application.ports.geography import CountryCatalog
from disaster_monitor.application.services.disaster_query_parser import (
    DisasterQueryParser,
)

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
    ) -> None:
        self._country_catalog = country_catalog
        self._query_parser = query_parser
        self._tools = tool_registry
        self._agent_model = agent_model

    async def run(self, question: str) -> AgentExecutionState:
        model_calls = 0
        draft = deterministic_task_draft(question)
        if self._agent_model is not None:
            try:
                draft = await self._agent_model.interpret(question)
                model_calls += 1
            except Exception:
                model_calls += 1
        task = validate_disaster_task(
            question,
            draft,
            country_catalog=self._country_catalog,
            query_parser=self._query_parser,
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

        plan = default_investigation_plan(task)
        if self._agent_model is not None and model_calls < MAX_MODEL_CALLS:
            try:
                proposed = await self._agent_model.propose_plan(
                    task,
                    tuple(item.planning_text() for item in self._tools.descriptions),
                )
                model_calls += 1
                plan = validate_plan(proposed, allowed_tools=self._tools.names)
            except Exception:
                model_calls += 1
                plan = default_investigation_plan(task)
        state = AgentExecutionState(task, plan, model_call_count=model_calls)
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
