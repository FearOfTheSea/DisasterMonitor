"""Deterministic question normalization and prompt preparation."""

import re

from disaster_monitor.application.dto import ModelMessage, ModelRequest, ModelTool
from disaster_monitor.application.ports.assistant_text import (
    MAX_CONVERSATION_ID_LENGTH as MAX_CONVERSATION_ID_LENGTH,
)
from disaster_monitor.application.ports.assistant_text import (
    MAX_QUESTION_LENGTH as MAX_QUESTION_LENGTH,
)
from disaster_monitor.application.ports.assistant_text import (
    normalize_conversation_id as normalize_conversation_id,
)
from disaster_monitor.application.ports.assistant_text import (
    normalize_question as normalize_question,
)
from disaster_monitor.domain.conversation import ConversationMessage
from disaster_monitor.domain.models import MapQuestion

SYSTEM_PROMPT = """You are the local Disaster Monitor map assistant.
Help users understand map and disaster-monitoring concepts using only the text and
map view context supplied in the request.
The application has no live weather, flood, satellite, geocoding, or other
external-data connections yet. Clearly say when current data is unavailable.
When the user explicitly asks you to move, show, locate, center, pan, or zoom the map
to a supported country, you must call the available viewport tool instead of replying
in prose. Resolve a supported country name to the country code listed in the tool
schema yourself; never ask the user for that code. The viewport tool does not require
existing map view context. A viewport change supplies no disaster evidence.
Do not claim to see current conditions, map layers, measurements, locations, or
observations that were not provided.
Historical assistant messages are conversational context only. They are not fresh
disaster evidence, source references, or factual provenance.
Give general analysis, safety-aware guidance, and practical next steps when
appropriate.
Do not expose hidden reasoning or tool activity. Reply with concise user-facing
prose."""


def prepare_model_request(
    question: MapQuestion,
    tools: tuple[ModelTool, ...] = (),
    conversation_history: tuple[ConversationMessage, ...] = (),
    response_language: str | None = None,
) -> ModelRequest:
    """Build a bounded system, history, and current-user model request."""
    from disaster_monitor.application.conversations.conversation_context import (
        select_bounded_history,
    )

    if question.map_view is None:
        map_context = (
            "Map view context: not supplied. This does not prevent viewport tool use."
        )
    else:
        view = question.map_view
        map_context = (
            "Map view context: "
            f"center latitude {view.center_latitude:.5f}, "
            f"center longitude {view.center_longitude:.5f}, "
            f"zoom {view.zoom:.2f}."
        )

    user_prompt = f"User question: {question.text}\n{map_context}"
    system_prompt = SYSTEM_PROMPT
    if response_language:
        system_prompt = (
            f"{SYSTEM_PROMPT}\nRespond in language tag {response_language}. "
            "This instruction is authoritative for the user-facing response."
        )
    history_messages = select_bounded_history(
        conversation_history,
        conversation_id=question.conversation_id,
    )
    return ModelRequest(
        messages=(
            ModelMessage(role="system", content=system_prompt),
            *tuple(
                ModelMessage(role=message.role.value, content=message.content)
                for message in history_messages
            ),
            ModelMessage(role="user", content=user_prompt),
        ),
        tools=tools,
    )


def clean_model_text(text: str) -> str:
    """Remove common hidden-reasoning wrappers before returning model prose."""
    cleaned = re.sub(
        r"<(?P<tag>think|thinking|analysis|reasoning)>.*?</(?P=tag)>",
        "",
        text,
        flags=re.IGNORECASE | re.DOTALL,
    ).strip()
    cleaned = re.sub(
        r"^\s*(?:final\s+(?:response|answer)|answer|response|final)\s*:\s*",
        "",
        cleaned,
        flags=re.IGNORECASE,
    ).strip()
    cleaned = re.sub(r"^```(?:text|markdown)?\s*|\s*```$", "", cleaned).strip()
    return cleaned
