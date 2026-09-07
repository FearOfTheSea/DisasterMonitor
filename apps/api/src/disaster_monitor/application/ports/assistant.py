"""Conversation-owned seam for executing a request-scoped assistant response."""

from typing import Protocol

from disaster_monitor.application.dto import AssistantAnswer
from disaster_monitor.application.multimodal import AssetAdmissionInput
from disaster_monitor.domain.conversation import ConversationMessage
from disaster_monitor.domain.models import MapView


class AssistantResponder(Protocol):
    async def execute(
        self,
        question: str,
        conversation_id: str | None = None,
        map_view: MapView | None = None,
        multimodal_inputs: tuple[AssetAdmissionInput, ...] = (),
        conversation_history: tuple[ConversationMessage, ...] = (),
    ) -> AssistantAnswer: ...
