"""Persist one assistant turn around the existing request-scoped assistant flow."""

import logging
from collections.abc import Callable
from datetime import UTC, datetime
from uuid import uuid4

from disaster_monitor.application.assistant_message_payload import (
    assistant_message_payload,
)
from disaster_monitor.application.dto import AssistantAnswer
from disaster_monitor.application.multimodal import AssetAdmissionInput
from disaster_monitor.application.ports.conversation_store import ConversationStore
from disaster_monitor.application.ports.memory_store import MemoryStore
from disaster_monitor.application.services.memory_policy import MemoryPolicy
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

logger = logging.getLogger(__name__)


class RunConversationTurn:
    """Load, execute, and persist one conversation-scoped assistant turn."""

    def __init__(
        self,
        assistant: AnswerMapQuestion,
        conversations: ConversationStore,
        *,
        clock: Callable[[], datetime] | None = None,
        memory_store: MemoryStore | None = None,
        memory_policy: MemoryPolicy | None = None,
        memory_enabled: bool = False,
    ) -> None:
        self._assistant = assistant
        self._conversations = conversations
        self._clock = clock or (lambda: datetime.now(UTC))
        self._memory_store = memory_store
        self._memory_policy = memory_policy or MemoryPolicy()
        self._memory_enabled = memory_enabled

    async def execute(
        self,
        question: str,
        conversation_id: str | None = None,
        map_view: MapView | None = None,
        multimodal_inputs: tuple[AssetAdmissionInput, ...] = (),
    ) -> AssistantAnswer:
        normalized_question = normalize_question(question)
        stored_conversation_id = self._conversation_id(conversation_id)
        previous_messages: tuple[ConversationMessage, ...] = ()
        if conversation_id is None:
            now = self._clock()
            await self._conversations.create(
                Conversation(
                    conversation_id=stored_conversation_id,
                    created_at=now,
                    updated_at=now,
                )
            )
        else:
            stored_conversation = await self._conversations.get(stored_conversation_id)
            if stored_conversation is None:
                raise ConversationNotFoundError(stored_conversation_id)
            previous_messages = stored_conversation.messages

        user_message = ConversationMessage(
            message_id=str(uuid4()),
            conversation_id=stored_conversation_id,
            role=ConversationRole.USER,
            content=normalized_question,
            created_at=self._clock(),
        )
        await self._conversations.append(user_message)
        result = await self._assistant.execute(
            question=normalized_question,
            conversation_id=stored_conversation_id,
            map_view=map_view,
            multimodal_inputs=multimodal_inputs,
            conversation_history=previous_messages,
        )
        assistant_message = ConversationMessage(
            message_id=str(uuid4()),
            conversation_id=stored_conversation_id,
            role=ConversationRole.ASSISTANT,
            content=result.message,
            created_at=self._clock(),
            assistant_payload=assistant_message_payload(result),
        )
        await self._conversations.append(assistant_message)
        await self._persist_memory(result, user_message, assistant_message)
        return result

    async def _persist_memory(
        self,
        result: AssistantAnswer,
        user_message: ConversationMessage,
        assistant_message: ConversationMessage,
    ) -> None:
        investigation = result.investigation
        if (
            not self._memory_enabled
            or self._memory_store is None
            or investigation is None
            or investigation.physical_event_id is None
            or investigation.evidence_state_version is None
            or investigation.disaster is None
            or investigation.country is None
        ):
            return
        try:
            candidate = self._memory_policy.candidate_for_investigation(
                conversation_id=user_message.conversation_id,
                physical_event_id=investigation.physical_event_id,
                disaster_identifier=investigation.disaster,
                country_code=investigation.country,
                source_message_ids=(
                    user_message.message_id,
                    assistant_message.message_id,
                ),
                evidence_ids=(investigation.physical_event_id,),
                world_state_version=investigation.evidence_state_version,
                now=self._clock(),
            )
            existing = await self._memory_store.list_for_scope(
                user_message.conversation_id,
                investigation.physical_event_id,
            )
            decision = self._memory_policy.evaluate(
                candidate, existing, now=self._clock()
            )
            if decision.record is not None:
                await self._memory_store.save(
                    decision.record,
                    superseded_memory_ids=decision.superseded_memory_ids,
                )
        except Exception:
            logger.exception("Typed historical-memory persistence failed")

    @staticmethod
    def _conversation_id(conversation_id: str | None) -> str:
        if conversation_id is None:
            return str(uuid4())
        return normalize_conversation_id(conversation_id)
