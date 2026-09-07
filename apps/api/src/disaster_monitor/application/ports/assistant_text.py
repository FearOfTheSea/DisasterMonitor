"""Shared admission rules for assistant text boundaries."""

import re
import unicodedata

from disaster_monitor.domain.errors import InvalidQuestionError

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
