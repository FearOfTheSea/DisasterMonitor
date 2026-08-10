"""The assistant's main application use case."""

from uuid import uuid4

from disaster_monitor.application.dto import AssistantAnswer
from disaster_monitor.application.multimodal import AssetAdmissionInput
from disaster_monitor.application.ports.language_model import LanguageModel
from disaster_monitor.application.services.current_disaster_report import (
    CurrentDisasterReportService,
)
from disaster_monitor.application.services.disaster_query_parser import (
    DisasterQueryParser,
)
from disaster_monitor.application.services.prompt_preparation import (
    clean_model_text,
    normalize_conversation_id,
    normalize_question,
    prepare_model_request,
)
from disaster_monitor.application.use_cases.run_disaster_agent import RunDisasterAgent
from disaster_monitor.domain.errors import ModelResponseError, ModelRuntimeError
from disaster_monitor.domain.models import MapQuestion, MapView


class AnswerMapQuestion:
    """Validate, prepare, and answer one map-related question."""

    def __init__(
        self,
        language_model: LanguageModel,
        current_disaster_report: CurrentDisasterReportService | None = None,
        disaster_query_parser: DisasterQueryParser | None = None,
        disaster_agent: RunDisasterAgent | None = None,
    ) -> None:
        self._language_model = language_model
        self._current_disaster_report = current_disaster_report
        self._disaster_query_parser = disaster_query_parser
        self._disaster_agent = disaster_agent

    async def execute(
        self,
        question: str,
        conversation_id: str | None = None,
        map_view: MapView | None = None,
        multimodal_inputs: tuple[AssetAdmissionInput, ...] = (),
    ) -> AssistantAnswer:
        """Return a stable answer while keeping model details behind the port."""
        if self._disaster_agent is not None:
            return await self._disaster_agent.execute(
                question,
                conversation_id=conversation_id,
                map_view=map_view,
                multimodal_inputs=multimodal_inputs,
            )
        normalized_question = normalize_question(question)
        normalized_conversation_id = normalize_conversation_id(conversation_id)
        classification = (
            self._disaster_query_parser.classify(normalized_question)
            if self._disaster_query_parser is not None
            else None
        )
        if (
            classification is not None
            and classification.request_type.value == "current_disaster"
        ):
            if self._current_disaster_report is None:
                raise ModelResponseError(
                    "The current-disaster workflow is not configured."
                )
            if classification.query is None:
                raise ModelResponseError("The disaster query could not be normalized.")
            report = await self._current_disaster_report.execute(classification.query)
            return AssistantAnswer(
                message=report.message,
                conversation_id=(
                    normalized_conversation_id
                    if normalized_conversation_id != "local-session"
                    else str(uuid4())
                ),
                model="source-backed-report",
                response_type=report.response_type,
                selected_event=report.selected_event,
                retrieval_time=report.retrieval_time,
                sources=report.sources,
                warnings=report.warnings,
                sections=report.sections,
                partial=report.partial,
            )
        request = prepare_model_request(
            MapQuestion(
                text=normalized_question,
                conversation_id=normalized_conversation_id,
                map_view=map_view,
            )
        )
        try:
            model_response = await self._language_model.generate(request)
        except ModelRuntimeError:
            raise
        except Exception as error:
            raise ModelRuntimeError(
                "The local model runtime could not answer the question."
            ) from error

        message = clean_model_text(model_response.text)
        if not message:
            raise ModelResponseError("The local model returned an empty response.")

        return AssistantAnswer(
            message=message,
            conversation_id=normalized_conversation_id
            if normalized_conversation_id != "local-session"
            else str(uuid4()),
            model=model_response.model,
        )
