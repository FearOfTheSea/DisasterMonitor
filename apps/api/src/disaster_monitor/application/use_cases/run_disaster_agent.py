"""Agent-first assistant use case and safe general-model delegation."""

from uuid import uuid4

from disaster_monitor.application.agent.models import AgentExecutionState, TaskKind
from disaster_monitor.application.agent.runtime import DisasterAgentRuntime
from disaster_monitor.application.dto import AssistantAnswer, InvestigationSummary
from disaster_monitor.application.ports.language_model import LanguageModel
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
        self, runtime: DisasterAgentRuntime, general_model: LanguageModel
    ) -> None:
        self._runtime = runtime
        self._general_model = general_model

    async def execute(
        self,
        question: str,
        conversation_id: str | None = None,
        map_view: MapView | None = None,
    ) -> AssistantAnswer:
        normalized = normalize_question(question)
        conversation = normalize_conversation_id(conversation_id)
        state = await self._runtime.run(normalized)
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
                response_type=(
                    "current_disaster_clarification"
                    if state.final_status.value == "clarification_required"
                    else "current_disaster_coverage_unavailable"
                ),
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


def _summary(state: AgentExecutionState) -> InvestigationSummary:
    task = state.task
    packet = state.workspace.evidence_packet
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
    )
