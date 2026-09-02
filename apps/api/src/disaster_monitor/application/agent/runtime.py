"""Small request-scoped disaster-agent runtime with explicit budgets."""

import copy

from disaster_monitor.application.agent.models import (
    AgentExecutionState,
    AgentReview,
    AgentStatus,
    EvidenceWorkspace,
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
    follow_up_plan,
    validate_plan,
)
from disaster_monitor.application.agent.sufficiency import (
    EvidenceSufficiencyAssessment,
    EvidenceSufficiencyState,
    assess_evidence_sufficiency,
    follow_up_option,
)
from disaster_monitor.application.agent.task_normalization import (
    deterministic_task_draft,
    is_obvious_non_disaster_map_question,
    validate_disaster_task,
)
from disaster_monitor.application.agent.tooling import ToolRegistry, execute_plan
from disaster_monitor.application.agent.trace import ExecutionTrace, TraceEventKind
from disaster_monitor.application.disaster import GeographicScope, ProviderIssue
from disaster_monitor.application.ports.agent_model import AgentModel
from disaster_monitor.application.ports.geography import CountryCatalog
from disaster_monitor.application.services.disaster_query_parser import (
    DisasterQueryParser,
)
from disaster_monitor.application.services.worldwide_disaster import (
    WorldwideDisasterReportService,
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
    ) -> None:
        self._country_catalog = country_catalog
        self._query_parser = query_parser
        self._tools = tool_registry
        self._agent_model = agent_model
        self._worldwide_report = worldwide_report

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

        assessment = self._assess(state, "initial")
        review = await self._review(
            state,
            assessment,
            interpretation_failed=interpretation_failed,
        )
        if review is not None:
            await self._maybe_follow_up(state, assessment, review, multimodal_assets)

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
        self._assess(state, "initial")
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
    def _assess(
        state: AgentExecutionState, phase: str
    ) -> EvidenceSufficiencyAssessment:
        assessment = assess_evidence_sufficiency(state)
        state.sufficiency_assessment = assessment
        state.trace.record(
            TraceEventKind.SUFFICIENCY_ASSESSED,
            phase=phase,
            state=assessment.state.value,
            gaps=tuple(item.value for item in assessment.gap_codes),
            options=assessment.option_ids,
        )
        return assessment

    async def _review(
        self,
        state: AgentExecutionState,
        assessment: EvidenceSufficiencyAssessment,
        *,
        interpretation_failed: bool,
    ) -> AgentReview | None:
        if self._agent_model is None:
            state.trace.record(
                TraceEventKind.REVIEW_DECISION,
                decision=ReviewDecision.FINISH.value,
                source="no_model",
            )
            return None
        if interpretation_failed:
            state.trace.record(
                TraceEventKind.REVIEW_DECISION,
                decision=ReviewDecision.FINISH.value,
                source="interpretation_failure",
            )
            return None
        if state.model_call_count >= MAX_MODEL_CALLS:
            state.trace.record(
                TraceEventKind.REVIEW_DECISION,
                decision=ReviewDecision.FINISH.value,
                source="model_budget",
            )
            return None
        try:
            review = await self._agent_model.review_progress(state.task, assessment)
        except Exception:
            state.model_call_count += 1
            state.trace.record(
                TraceEventKind.MODEL_FAILED,
                operation="review_progress",
                counted=True,
            )
            state.trace.record(
                TraceEventKind.REVIEW_DECISION,
                decision=ReviewDecision.FINISH.value,
                source="invalid_model",
            )
            return None
        state.model_call_count += 1
        state.trace.record(
            TraceEventKind.MODEL_COMPLETED,
            operation="review_progress",
            counted=True,
        )
        if not isinstance(review, AgentReview) or not isinstance(
            review.decision, ReviewDecision
        ):
            state.trace.record(
                TraceEventKind.REVIEW_DECISION,
                decision=ReviewDecision.FINISH.value,
                source="invalid_model",
            )
            return None
        state.trace.record(
            TraceEventKind.REVIEW_DECISION,
            decision=review.decision.value,
            selected=review.selected_follow_up_option_id or "",
        )
        return review

    async def _maybe_follow_up(
        self,
        state: AgentExecutionState,
        assessment: EvidenceSufficiencyAssessment,
        review: AgentReview,
        multimodal_assets: tuple[MultimodalAsset, ...],
    ) -> None:
        selected_id = review.selected_follow_up_option_id
        allowed = set(assessment.option_ids)
        if (
            review.decision is not ReviewDecision.REPLAN
            or not isinstance(selected_id, str)
            or selected_id not in allowed
            or state.replan_count >= MAX_REPLANS
            or assessment.state is not EvidenceSufficiencyState.FOLLOWUP_AVAILABLE
        ):
            if review.decision is ReviewDecision.REPLAN:
                self._reject_follow_up(state, selected_id or "invalid")
            return
        option = follow_up_option(selected_id)
        if option is None:
            self._reject_follow_up(state, selected_id)
            return
        try:
            candidate = follow_up_plan(selected_id, replan_number=1)
            validated = validate_plan(
                candidate,
                allowed_tools=self._tools.names,
                # The initial plan already passed the multimodal safety gate;
                # recovery only reruns the source/evidence stages.
                requires_multimodal=False,
                prior_tools=frozenset(step.tool_name for step in state.plan.steps),
                allow_followup=True,
                require_composition=False,
            )
        except Exception:
            self._reject_follow_up(state, selected_id)
            return

        state.replan_count = 1
        state.followup_plan = validated
        state.trace.record(
            TraceEventKind.FOLLOWUP_SELECTED,
            option_id=option.option_id,
        )
        state.trace.record(
            TraceEventKind.FOLLOWUP_PLAN_VALIDATED,
            step_count=len(validated.steps),
            tools=tuple(step.tool_name for step in validated.steps),
        )
        workspace_before = copy.copy(state.workspace)
        workspace_before.source_ids = list(state.workspace.source_ids)
        warnings_before = list(state.warnings)
        self._remove_retryable_warnings(state, assessment)
        try:
            await execute_plan(
                state,
                self._tools,
                plan=validated,
                trace_phase="followup",
            )
        except Exception:
            self._restore_after_failed_retry(state, workspace_before, warnings_before)
            state.trace.record(
                TraceEventKind.FOLLOWUP_EXECUTED,
                option_id=option.option_id,
                result="failed",
            )
        else:
            if self._retry_should_restore(state, option.option_id, workspace_before):
                self._restore_after_failed_retry(
                    state, workspace_before, warnings_before
                )
            state.trace.record(
                TraceEventKind.FOLLOWUP_EXECUTED,
                option_id=option.option_id,
                result="completed",
            )
        self._assess(state, "followup")

    @staticmethod
    def _retry_should_restore(
        state: AgentExecutionState,
        option_id: str,
        workspace_before: EvidenceWorkspace,
    ) -> bool:
        batch = (
            state.workspace.event_batch
            if option_id == "retry_event_discovery"
            else state.workspace.situation_batch
        )
        if option_id == "retry_situation_evidence":
            return workspace_before.evidence_packet is not None and (
                batch is None or not batch.records or bool(batch.issues)
            )
        return batch is not None and any(issue.retryable for issue in batch.issues)

    @staticmethod
    def _restore_after_failed_retry(
        state: AgentExecutionState,
        workspace_before: EvidenceWorkspace,
        warnings_before: list[str],
    ) -> None:
        state.workspace = workspace_before
        state.warnings = warnings_before
        state.warnings.append(
            "The permitted retry failed; first-pass evidence was retained."
        )
        state.capability_gaps.append(
            "A permitted evidence retry failed; first-pass evidence was retained."
        )

    @staticmethod
    def _remove_retryable_warnings(
        state: AgentExecutionState,
        assessment: EvidenceSufficiencyAssessment,
    ) -> None:
        if not assessment.follow_up_options:
            return
        issues: tuple[ProviderIssue, ...] = ()
        if state.workspace.event_batch is not None:
            issues += tuple(
                issue for issue in state.workspace.event_batch.issues if issue.retryable
            )
        if state.workspace.situation_batch is not None:
            issues += tuple(
                issue
                for issue in state.workspace.situation_batch.issues
                if issue.retryable
            )
        retry_messages = {issue.message for issue in issues}
        state.warnings[:] = [
            warning for warning in state.warnings if warning not in retry_messages
        ]

    @staticmethod
    def _reject_follow_up(state: AgentExecutionState, selected_id: str) -> None:
        state.warnings.append(
            "The investigation review selected no permitted follow-up; the "
            "admitted evidence was retained."
        )
        state.trace.record(
            TraceEventKind.FOLLOWUP_REJECTED,
            option_id=selected_id,
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
