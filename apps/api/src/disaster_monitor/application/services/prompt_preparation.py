"""Deterministic question normalization and prompt preparation."""

import re
import unicodedata

from disaster_monitor.application.dto import ModelMessage, ModelRequest, ModelTool
from disaster_monitor.domain.errors import InvalidQuestionError
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
Give general analysis, safety-aware guidance, and practical next steps when
appropriate.
Do not expose hidden reasoning or tool activity. Reply with concise user-facing
prose."""

_WHITESPACE = re.compile(r"\s+")
_CONTROL_CHARACTERS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
MAX_QUESTION_LENGTH = 2_000
MAX_CONVERSATION_ID_LENGTH = 100


def normalize_question(raw_question: str) -> str:
    """Normalize user text and enforce the MVP's deterministic limits."""
    normalized = unicodedata.normalize("NFKC", raw_question)
    normalized = _CONTROL_CHARACTERS.sub(" ", normalized)
    normalized = _WHITESPACE.sub(" ", normalized).strip()
    if not normalized:
        raise InvalidQuestionError("Question must contain at least one character.")
    if len(normalized) > MAX_QUESTION_LENGTH:
        raise InvalidQuestionError(
            f"Question must be {MAX_QUESTION_LENGTH} characters or fewer."
        )
    return normalized


def normalize_conversation_id(raw_conversation_id: str | None) -> str:
    """Normalize a browser session identifier without persisting it server-side."""
    if raw_conversation_id is None:
        return "local-session"
    normalized = _WHITESPACE.sub(" ", raw_conversation_id).strip()
    if not normalized:
        return "local-session"
    if len(normalized) > MAX_CONVERSATION_ID_LENGTH:
        raise InvalidQuestionError(
            f"Conversation ID must be {MAX_CONVERSATION_ID_LENGTH} characters or fewer."
        )
    return normalized


def prepare_model_request(
    question: MapQuestion, tools: tuple[ModelTool, ...] = ()
) -> ModelRequest:
    """Build the stable system and user messages sent to any model adapter."""
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
    return ModelRequest(
        messages=(
            ModelMessage(role="system", content=SYSTEM_PROMPT),
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
