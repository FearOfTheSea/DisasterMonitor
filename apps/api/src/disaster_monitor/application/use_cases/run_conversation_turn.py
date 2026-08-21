"""Persist one assistant turn around the existing request-scoped assistant flow."""

from collections.abc import Callable
from datetime import UTC, datetime
from uuid import uuid4

from disaster_monitor.application.dto import AssistantAnswer
from disaster_monitor.application.multimodal import AssetAdmissionInput
from disaster_monitor.application.ports.conversation_store import ConversationStore
from disaster_monitor.application.services.prompt_preparation import (
    normalize_conversation_id,
    normalize_question,
)
from disaster_monitor.application.use_cases.answer_map_question import AnswerMapQuestion
from disaster_monitor.domain.conversation import (
    Conversation,
    ConversationMessage,
    ConversationRole,
)
from disaster_monitor.domain.errors import ConversationNotFoundError
from disaster_monitor.domain.models import MapView


class RunConversationTurn:
    """Save transcript text without adding history to model or agent requests."""

    def __init__(
        self,
        assistant: AnswerMapQuestion,
        conversations: ConversationStore,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._assistant = assistant
        self._conversations = conversations
        self._clock = clock or (lambda: datetime.now(UTC))

    async def execute(
        self,
        question: str,
        conversation_id: str | None = None,
        map_view: MapView | None = None,
        multimodal_inputs: tuple[AssetAdmissionInput, ...] = (),
    ) -> AssistantAnswer:
        normalized_question = normalize_question(question)
        stored_conversation_id = self._conversation_id(conversation_id)
        if conversation_id is None:
            now = self._clock()
            await self._conversations.create(
                Conversation(
                    conversation_id=stored_conversation_id,
                    created_at=now,
                    updated_at=now,
                )
            )
        elif await self._conversations.get(stored_conversation_id) is None:
            raise ConversationNotFoundError(stored_conversation_id)

        await self._conversations.append(
            ConversationMessage(
                message_id=str(uuid4()),
                conversation_id=stored_conversation_id,
                role=ConversationRole.USER,
                content=normalized_question,
                created_at=self._clock(),
            )
        )
        result = await self._assistant.execute(
            question=normalized_question,
            conversation_id=stored_conversation_id,
            map_view=map_view,
            multimodal_inputs=multimodal_inputs,
        )
        await self._conversations.append(
            ConversationMessage(
                message_id=str(uuid4()),
                conversation_id=stored_conversation_id,
                role=ConversationRole.ASSISTANT,
                content=result.message,
                created_at=self._clock(),
            )
        )
        return result

    @staticmethod
    def _conversation_id(conversation_id: str | None) -> str:
        if conversation_id is None:
            return str(uuid4())
        return normalize_conversation_id(conversation_id)
