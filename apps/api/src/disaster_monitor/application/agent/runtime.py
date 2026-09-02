"""Small request-scoped disaster-agent runtime with explicit budgets."""

from disaster_monitor.application.agent.models import (
    AgentExecutionState,
    AgentStatus,
    InvestigationAction,
    InvestigationPlan,
    PlanStatus,
    ReviewDecision,
    TaskKind,
    ValidatedDisasterTask,
    ValidationStatus,
)
from disaster_monitor.application.agent.planning import (
    default_investigation_plan,
    validate_plan,
)
from disaster_monitor.application.agent.runtime_review import (
    MAX_MODEL_CALLS,
    AgentReviewCoordinator,
)
from disaster_monitor.application.agent.task_normalization import (
    deterministic_task_draft,
    is_obvious_non_disaster_map_question,
    validate_disaster_task,
)
from disaster_monitor.application.agent.tooling import ToolRegistry, execute_plan
from disaster_monitor.application.agent.trace import ExecutionTrace, TraceEventKind
from disaster_monitor.application.disaster import GeographicScope
from disaster_monitor.application.ports.agent_model import AgentModel
from disaster_monitor.application.ports.geography import CountryCatalog
from disaster_monitor.application.services.disaster_query_parser import (
    DisasterQueryParser,
)
from disaster_monitor.application.services.worldwide_disaster import (
    WorldwideDisasterReportService,
)
from disaster_monitor.domain.multimodal import MultimodalAsset


class DisasterAgentRuntime:
    def __init__(
        self,
        *,
        country_catalog: CountryCatalog,
        query_parser: DisasterQueryParser,
        tool_registry: ToolRegistry,
        agent_model: AgentModel | None = None,
        worldwide_report: WorldwideDisasterReportService | None = None,
    ) -> None:
        self._country_catalog = country_catalog
        self._query_parser = query_parser
        self._tools = tool_registry
        self._agent_model = agent_model
        self._worldwide_report = worldwide_report
        self._reviews = AgentReviewCoordinator(agent_model, tool_registry)

    async def run(
        self,
        question: str,
        *,
        conversation_id: str | None = None,
        multimodal_assets: tuple[MultimodalAsset, ...] = (),
    ) -> AgentExecutionState:
        trace = ExecutionTrace()
        pending_model_events: list[tuple[TraceEventKind, str, bool]] = []
        model_calls = 0
        interpretation_failed = False
        if self._agent_model is not None and not is_obvious_non_disaster_map_question(
            question
        ):
            try:
                draft = await self._agent_model.interpret(question)
                counted = draft.canonical
                if counted:
                    model_calls += 1
                pending_model_events.append(
                    (TraceEventKind.MODEL_COMPLETED, "interpret", counted)
                )
            except Exception:
                interpretation_failed = True
                pending_model_events.append(
                    (TraceEventKind.MODEL_FAILED, "interpret", False)
                )
                draft = deterministic_task_draft(question)
        else:
            draft = deterministic_task_draft(question)
        task = validate_disaster_task(
            question,
            draft,
            country_catalog=self._country_catalog,
            query_parser=self._query_parser,
        )
        empty_plan = InvestigationPlan(
            "no-plan", task.question, (), status=PlanStatus.COMPLETED
        )

        if task.investigation_targets:
            if multimodal_assets:
                task = ValidatedDisasterTask(
                    question=task.question,
                    kind=TaskKind.INVESTIGATION,
                    requires_evidence=True,
                    validation_status=ValidationStatus.CLARIFICATION_REQUIRED,
                    detail=(
                        "Investigation Agent v1 does not admit multimodal assets for "
                        "a two-hazard investigation."
                    ),
                    information_needs=task.information_needs,
                    output_modalities=task.output_modalities,
                    response_language=task.response_language,
                    response_language_explicit=task.response_language_explicit,
                    operator_action_ids=task.operator_action_ids,
                )
            else:
                from disaster_monitor.application.agent.investigation_runtime import (
                    InvestigationRuntime,
                )

                return await InvestigationRuntime(self).execute(
                    task,
                    conversation_id=conversation_id,
                    model_call_count=model_calls,
                    model_events=pending_model_events,
                )

        if task.kind in {TaskKind.NON_DISASTER, TaskKind.GENERAL_KNOWLEDGE}:
            state = self._state(
                task,
                empty_plan,
                conversation_id=conversation_id,
                model_call_count=model_calls,
                trace=trace,
            )
            self._record_task_and_models(state, pending_model_events)
            state.final_status = AgentStatus.DELEGATED
            self._terminate(state, task.kind.value)
            return state
        if task.validation_status != ValidationStatus.VALID:
            state = self._state(
                task,
                empty_plan,
                conversation_id=conversation_id,
                model_call_count=model_calls,
                trace=trace,
            )
            self._record_task_and_models(state, pending_model_events)
            state.final_status = AgentStatus.CLARIFICATION_REQUIRED
            if task.validation_status == ValidationStatus.CATALOG_LIMITATION:
                state.final_status = AgentStatus.COVERAGE_UNAVAILABLE
            state.capability_gaps.append(
                task.detail or "Task validation is incomplete."
            )
            self._terminate(state, task.validation_status.value)
            return state

        if task.geographic_scope is GeographicScope.WORLDWIDE:
            state = self._state(
                task,
                empty_plan,
                conversation_id=conversation_id,
                model_call_count=model_calls,
                trace=trace,
            )
            self._record_task_and_models(state, pending_model_events)
            if self._worldwide_report is None or task.worldwide_query is None:
                state.final_status = AgentStatus.COVERAGE_UNAVAILABLE
                state.capability_gaps.append(
                    "No worldwide event-reporting capability is configured."
                )
                self._terminate(state, "coverage_unavailable")
                return state
            try:
                state.workspace.report = await self._worldwide_report.execute(
                    task.worldwide_query,
                )
            except Exception:
                state.final_status = AgentStatus.FAILED
                state.warnings.append(
                    "The bounded worldwide investigation stopped safely."
                )
                self._terminate(state, "worldwide_execution_failed")
                return state
            state.actions.extend(
                InvestigationAction("worldwide", action)
                for action in state.workspace.report.investigation_actions
            )
            state.capability_gaps.extend(state.workspace.report.capability_gaps)
            state.workspace.source_ids.extend(
                source.source_id for source in state.workspace.report.sources
            )
            if state.workspace.report.selected_event is None:
                state.final_status = AgentStatus.COVERAGE_UNAVAILABLE
                termination_reason = (
                    state.workspace.report.termination_reason or "coverage_unavailable"
                )
            elif state.workspace.report.partial:
                state.final_status = AgentStatus.PARTIAL
                termination_reason = (
                    state.workspace.report.termination_reason
                    or "partial_event_evidence"
                )
            else:
                state.final_status = AgentStatus.COMPLETED
                termination_reason = (
                    state.workspace.report.termination_reason or "completed"
                )
            state.warnings.extend(state.workspace.report.warnings)
            self._terminate(state, termination_reason)
            return state

        plan = default_investigation_plan(
            task, multimodal_assets_available=bool(multimodal_assets)
        )
        plan_validated = False
        if self._agent_model is not None and model_calls < MAX_MODEL_CALLS:
            try:
                proposed = await self._agent_model.propose_plan(
                    task,
                    tuple(item.planning_text() for item in self._tools.descriptions),
                )
                model_calls += 1
                pending_model_events.append(
                    (TraceEventKind.MODEL_COMPLETED, "propose_plan", True)
                )
                plan = validate_plan(
                    proposed,
                    allowed_tools=self._tools.names,
                    requires_multimodal=bool(multimodal_assets),
                )
                plan_validated = True
            except Exception:
                if not pending_model_events or pending_model_events[-1][1] != (
                    "propose_plan"
                ):
                    pending_model_events.append(
                        (TraceEventKind.MODEL_FAILED, "propose_plan", True)
                    )
                    model_calls += 1
                else:
                    pending_model_events[-1] = (
                        TraceEventKind.MODEL_FAILED,
                        "propose_plan",
                        True,
                    )
                plan = default_investigation_plan(
                    task, multimodal_assets_available=bool(multimodal_assets)
                )
        if not plan_validated:
            try:
                plan = validate_plan(
                    plan,
                    allowed_tools=self._tools.names,
                    requires_multimodal=bool(multimodal_assets),
                )
                plan_validated = True
            except Exception:
                # The state still records the safe fallback plan; execution will
                # fail closed if a required allowlisted tool is absent.
                pass

        state = self._state(
            task,
            plan,
            conversation_id=conversation_id,
            model_call_count=model_calls,
            trace=trace,
        )
        self._record_task_and_models(state, pending_model_events)
        state.workspace.multimodal_assets = multimodal_assets
        state.capability_gaps.extend(plan.capability_gaps)
        if plan_validated:
            state.trace.record(
                TraceEventKind.INITIAL_PLAN_VALIDATED,
                step_count=len(plan.steps),
                tools=tuple(step.tool_name for step in plan.steps),
            )
        try:
            await execute_plan(
                state,
                self._tools,
                stop_before_composition=True,
                trace_phase="initial",
            )
        except Exception as error:
            state.final_status = AgentStatus.FAILED
            state.termination_reason = _safe_termination(error)
            state.warnings.append("The bounded investigation stopped safely.")
            self._terminate(state, state.termination_reason)
            return state

        assessment = self._reviews.assess(state, "initial")
        review = await self._reviews.review(
            state,
            assessment,
            interpretation_failed=interpretation_failed,
        )
        if review is not None:
            await self._reviews.maybe_follow_up(
                state, assessment, review, multimodal_assets
            )

        try:
            composition_step = next(
                step
                for step in state.plan.steps
                if step.tool_name == "compose_disaster_answer"
            )
            await execute_plan(
                state,
                self._tools,
                step_ids=(composition_step.step_id,),
                trace_phase="composition",
            )
            state.trace.record(
                TraceEventKind.COMPOSITION,
                step_id=composition_step.step_id,
            )
        except Exception as error:
            state.final_status = AgentStatus.FAILED
            state.termination_reason = _safe_termination(error)
            state.warnings.append("The bounded investigation stopped safely.")
            self._terminate(state, state.termination_reason)
            return state

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
        self._terminate(state, state.termination_reason)
        return state

    async def run_validated_task(
        self,
        task: ValidatedDisasterTask,
        *,
        conversation_id: str | None,
        initial_tool_call_count: int = 0,
        allow_model_backed_specialists: bool = True,
    ) -> AgentExecutionState:
        """Run one prevalidated single-hazard task without model orchestration.

        Investigation Agent v1 uses this narrow entry point for each already-built
        branch. It intentionally bypasses interpretation, planning proposals,
        review/replanning, visual work, and model-backed specialist findings.
        """
        if (
            task.validation_status is not ValidationStatus.VALID
            or task.disaster is None
            or task.query is None
            or task.investigation_targets
        ):
            raise ValueError("A validated single-hazard task is required.")
        plan = default_investigation_plan(task)
        state = self._state(
            task,
            plan,
            conversation_id=conversation_id,
            model_call_count=0,
            trace=ExecutionTrace(),
        )
        state.tool_call_count = initial_tool_call_count
        state.allow_model_backed_specialists = allow_model_backed_specialists
        self._record_task_and_models(state, [])
        try:
            validate_plan(
                plan,
                allowed_tools=self._tools.names,
                requires_multimodal=False,
            )
        except Exception as error:
            state.final_status = AgentStatus.FAILED
            state.capability_gaps.append(
                "The deterministic investigation plan is unavailable."
            )
            self._terminate(state, _safe_termination(error))
            return state
        state.trace.record(
            TraceEventKind.INITIAL_PLAN_VALIDATED,
            step_count=len(plan.steps),
            tools=tuple(step.tool_name for step in plan.steps),
        )
        try:
            await execute_plan(
                state,
                self._tools,
                stop_before_composition=True,
                trace_phase="investigation_branch",
            )
        except Exception as error:
            state.final_status = AgentStatus.FAILED
            state.warnings.append("The bounded investigation branch stopped safely.")
            self._terminate(state, _safe_termination(error))
            return state
        self._reviews.assess(state, "initial")
        state.trace.record(
            TraceEventKind.REVIEW_DECISION,
            decision=ReviewDecision.FINISH.value,
            source="investigation_default_plan",
        )
        try:
            composition_step = next(
                step
                for step in plan.steps
                if step.tool_name == "compose_disaster_answer"
            )
            await execute_plan(
                state,
                self._tools,
                step_ids=(composition_step.step_id,),
                trace_phase="investigation_branch_composition",
            )
            state.trace.record(
                TraceEventKind.COMPOSITION, step_id=composition_step.step_id
            )
        except Exception as error:
            state.final_status = AgentStatus.FAILED
            state.warnings.append("The bounded investigation branch stopped safely.")
            self._terminate(state, _safe_termination(error))
            return state
        self._set_final_status_from_report(state)
        self._terminate(state, state.termination_reason)
        return state

    @staticmethod
    def _state(
        task: ValidatedDisasterTask,
        plan: InvestigationPlan,
        *,
        conversation_id: str | None,
        model_call_count: int,
        trace: ExecutionTrace,
    ) -> AgentExecutionState:
        return AgentExecutionState(
            task,
            plan,
            conversation_id=conversation_id,
            model_call_count=model_call_count,
            trace=trace,
        )

    @staticmethod
    def _set_final_status_from_report(state: AgentExecutionState) -> None:
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

    @staticmethod
    def _record_task_and_models(
        state: AgentExecutionState,
        model_events: list[tuple[TraceEventKind, str, bool]],
    ) -> None:
        state.trace.record(
            TraceEventKind.TASK_VALIDATED,
            task_kind=state.task.kind.value,
            validation=state.task.validation_status.value,
        )
        for event_kind, operation, counted in model_events:
            state.trace.record(
                event_kind,
                operation=operation,
                counted=counted,
            )

    @staticmethod
    def _terminate(state: AgentExecutionState, reason: str) -> None:
        state.termination_reason = reason
        state.trace.record(TraceEventKind.TERMINATION, reason=reason)


def _safe_termination(error: Exception) -> str:
    text = str(error).lower()
    if "budget" in text:
        return "tool_call_budget_exhausted"
    if "prerequisite" in text or "sequencing" in text:
        return "invalid_tool_sequencing"
    if "unknown agent tool" in text:
        return "unknown_tool"
    return "tool_execution_failed"
