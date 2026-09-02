"""Evidence review and the single bounded follow-up policy."""

import copy

from disaster_monitor.application.agent.models import (
    AgentExecutionState,
    AgentReview,
    EvidenceWorkspace,
    ReviewDecision,
)
from disaster_monitor.application.agent.planning import (
    follow_up_plan,
    validate_follow_up_plan,
)
from disaster_monitor.application.agent.sufficiency import (
    EvidenceSufficiencyAssessment,
    EvidenceSufficiencyState,
    assess_evidence_sufficiency,
    follow_up_option,
)
from disaster_monitor.application.agent.tooling import ToolRegistry, execute_plan
from disaster_monitor.application.agent.trace import TraceEventKind
from disaster_monitor.application.disaster import ProviderIssue
from disaster_monitor.application.ports.agent_model import AgentModel
from disaster_monitor.domain.multimodal import MultimodalAsset

MAX_MODEL_CALLS = 4
MAX_REPLANS = 1


class AgentReviewCoordinator:
    def __init__(self, agent_model: AgentModel | None, tools: ToolRegistry) -> None:
        self._agent_model = agent_model
        self._tools = tools

    @staticmethod
    def assess(state: AgentExecutionState, phase: str) -> EvidenceSufficiencyAssessment:
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

    async def review(
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

    async def maybe_follow_up(
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
            validated = validate_follow_up_plan(
                candidate,
                allowed_tools=self._tools.names,
                prior_tools=frozenset(step.tool_name for step in state.plan.steps),
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
        self.assess(state, "followup")

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
