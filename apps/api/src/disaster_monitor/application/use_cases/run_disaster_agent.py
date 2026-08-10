"""Agent-first assistant use case and safe general-model delegation."""

from uuid import uuid4

from disaster_monitor.application.agent.models import (
    AgentExecutionState,
    AgentStatus,
    TaskKind,
)
from disaster_monitor.application.agent.runtime import DisasterAgentRuntime
from disaster_monitor.application.dto import AssistantAnswer, InvestigationSummary
from disaster_monitor.application.multimodal import AssetAdmissionInput
from disaster_monitor.application.ports.language_model import LanguageModel
from disaster_monitor.application.services.multimodal_asset_admission import (
    MultimodalAssetAdmissionService,
)
from disaster_monitor.application.services.prompt_preparation import (
    clean_model_text,
    normalize_conversation_id,
    normalize_question,
    prepare_model_request,
)
from disaster_monitor.domain.errors import ModelResponseError, ModelRuntimeError
from disaster_monitor.domain.models import MapQuestion, MapView


class RunDisasterAgent:
    def __init__(
        self,
        runtime: DisasterAgentRuntime,
        general_model: LanguageModel,
        asset_admission: MultimodalAssetAdmissionService | None = None,
    ) -> None:
        self._runtime = runtime
        self._general_model = general_model
        self._asset_admission = asset_admission

    async def execute(
        self,
        question: str,
        conversation_id: str | None = None,
        map_view: MapView | None = None,
        multimodal_inputs: tuple[AssetAdmissionInput, ...] = (),
    ) -> AssistantAnswer:
        normalized = normalize_question(question)
        conversation = normalize_conversation_id(conversation_id)
        assets = (
            self._asset_admission.admit_many(multimodal_inputs)
            if multimodal_inputs and self._asset_admission is not None
            else ()
        )
        state = (
            await self._runtime.run(normalized, multimodal_assets=assets)
            if assets
            else await self._runtime.run(normalized)
        )
        if state.task.kind in {TaskKind.NON_DISASTER, TaskKind.GENERAL_KNOWLEDGE}:
            return await self._general_answer(normalized, conversation, map_view)
        report = state.workspace.report
        if report is None:
            message = state.task.detail or (
                state.capability_gaps[0]
                if state.capability_gaps
                else "The disaster investigation could not produce a grounded answer."
            )
            return AssistantAnswer(
                message=message,
                conversation_id=_conversation_id(conversation),
                model="disaster-agent",
                response_type=_response_type_without_report(state.final_status),
                warnings=tuple(state.warnings),
                partial=True,
                investigation=_summary(state),
            )
        return AssistantAnswer(
            message=report.message,
            conversation_id=_conversation_id(conversation),
            model="source-backed-agent",
            response_type=report.response_type,
            selected_event=report.selected_event,
            retrieval_time=report.retrieval_time,
            sources=report.sources,
            warnings=report.warnings,
            sections=report.sections,
            partial=report.partial,
            investigation=_summary(state),
            multimodal_state=state.workspace.multimodal_state,
            common_operational_picture=state.workspace.common_operational_picture,
        )

    async def _general_answer(
        self, question: str, conversation: str, map_view: MapView | None
    ) -> AssistantAnswer:
        request = prepare_model_request(MapQuestion(question, conversation, map_view))
        try:
            response = await self._general_model.generate(request)
        except ModelRuntimeError:
            raise
        except Exception as error:
            raise ModelRuntimeError(
                "The local model runtime could not answer the question."
            ) from error
        message = clean_model_text(response.text)
        if not message:
            raise ModelResponseError("The local model returned an empty response.")
        return AssistantAnswer(message, _conversation_id(conversation), response.model)


def _conversation_id(value: str) -> str:
    return str(uuid4()) if value == "local-session" else value


def _response_type_without_report(status: AgentStatus) -> str:
    if status == AgentStatus.CLARIFICATION_REQUIRED:
        return "current_disaster_clarification"
    if status == AgentStatus.COVERAGE_UNAVAILABLE:
        return "current_disaster_coverage_unavailable"
    return "current_disaster_investigation_failed"


def _summary(state: AgentExecutionState) -> InvestigationSummary:
    task = state.task
    packet = state.workspace.evidence_packet
    priority = state.workspace.incident_priority
    decision = state.workspace.triage_decision
    decision_outcome = state.workspace.decision_outcome
    decision_state = (
        decision_outcome.final_state if decision_outcome is not None else None
    )
    collaboration = state.workspace.collaborative_investigation
    return InvestigationSummary(
        status=state.final_status.value,
        task_summary=(task.detail or task.question)[:500],
        hazard=task.hazard.value if task.hazard else None,
        country=task.country.alpha3_code if task.country else task.unresolved_place,
        information_needs=tuple(item.value for item in task.information_needs),
        output_modalities=tuple(item.value for item in task.output_modalities),
        actions=tuple(action.description for action in state.actions),
        source_ids=tuple(dict.fromkeys(state.workspace.source_ids)),
        evidence_count=len(packet.facts) if packet else 0,
        capability_gaps=tuple(
            dict.fromkeys((*state.capability_gaps, *state.plan.capability_gaps))
        ),
        termination_reason=state.termination_reason,
        triage_priority=priority.priority.value if priority else None,
        triage_score=priority.score if priority else None,
        triage_action=decision.action.value if decision else None,
        triage_autonomy_mode=decision.autonomy_mode.value if decision else None,
        triage_requires_human_intervention=(
            decision.requires_human_intervention if decision else None
        ),
        decision_action=(decision_outcome.action.value if decision_outcome else None),
        decision_autonomy_mode=(
            decision_outcome.autonomy_mode.value if decision_outcome else None
        ),
        decision_requires_human_intervention=(
            decision_outcome.requires_human_intervention if decision_outcome else None
        ),
        decision_termination_reason=(
            decision_outcome.termination_reason if decision_outcome else None
        ),
        decision_state_revision=(decision_state.revision if decision_state else None),
        decision_active_internal_states=(
            ()
            if decision_state is None
            else tuple(
                name
                for name, active in (
                    ("monitoring_active", decision_state.monitoring_active),
                    (
                        "evidence_gap_priority_active",
                        decision_state.evidence_gap_priority_active,
                    ),
                    (
                        "verified_update_comparison_active",
                        decision_state.verified_update_comparison_active,
                    ),
                )
                if active
            )
        ),
        specialist_handoff_count=len(state.workspace.specialist_handoffs),
        specialist_roles=tuple(
            dict.fromkeys(
                handoff.receiver_role.value
                for handoff in state.workspace.specialist_handoffs
            )
        ),
        collaboration_status=(collaboration.status.value if collaboration else None),
        collaboration_finding_count=(
            len(collaboration.findings) if collaboration else 0
        ),
        collaboration_deadlock_count=(
            len(collaboration.unresolved_deadlocks) if collaboration else 0
        ),
        collaboration_iterations=(collaboration.iterations if collaboration else None),
        collaboration_fallback_reason=(
            collaboration.fallback_reason if collaboration else None
        ),
    )
