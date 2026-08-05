"""The assistant's main application use case."""

from uuid import uuid4

from disaster_monitor.application.dto import AssistantAnswer
from disaster_monitor.application.ports.disaster_information import (
    DisasterInformationProvider,
)
from disaster_monitor.application.ports.language_model import LanguageModel
from disaster_monitor.application.services.current_disaster_information import (
    build_disaster_information_query,
    format_disaster_information_context,
    format_unavailable_disaster_information_context,
    requires_current_disaster_information,
)
from disaster_monitor.application.services.prompt_preparation import (
    clean_model_text,
    normalize_conversation_id,
    normalize_question,
    prepare_model_request,
)
from disaster_monitor.domain.errors import ModelResponseError, ModelRuntimeError
from disaster_monitor.domain.models import MapQuestion, MapView


class AnswerMapQuestion:
    """Validate, enrich, prepare, and answer one map-related question."""

    def __init__(
        self,
        language_model: LanguageModel,
        disaster_information_provider: DisasterInformationProvider | None = None,
    ) -> None:
        self._language_model = language_model
        self._disaster_information_provider = disaster_information_provider

    async def execute(
        self,
        question: str,
        conversation_id: str | None = None,
        map_view: MapView | None = None,
    ) -> AssistantAnswer:
        """Return a stable answer while keeping provider details behind ports."""
        normalized_question = normalize_question(question)
        normalized_conversation_id = normalize_conversation_id(conversation_id)
        disaster_information_context: str | None = None

        if requires_current_disaster_information(normalized_question):
            provider = self._disaster_information_provider
            if provider is None:
                disaster_information_context = (
                    format_unavailable_disaster_information_context()
                )
            else:
                try:
                    information = await provider.search(
                        build_disaster_information_query(normalized_question)
                    )
                    disaster_information_context = (
                        format_disaster_information_context(information)
                    )
                except Exception:
                    disaster_information_context = (
                        format_unavailable_disaster_information_context()
                    )

        request = prepare_model_request(
            MapQuestion(
                text=normalized_question,
                conversation_id=normalized_conversation_id,
                map_view=map_view,
            ),
            disaster_information_context=disaster_information_context,
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
