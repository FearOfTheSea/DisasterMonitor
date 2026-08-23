"""Framework-independent assistant conversation records."""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

type JsonValue = (
    None | bool | int | float | str | list["JsonValue"] | dict[str, "JsonValue"]
)


class ConversationRole(StrEnum):
    USER = "user"
    ASSISTANT = "assistant"


@dataclass(frozen=True, slots=True)
class AssistantMessagePayload:
    """Versioned application response state retained with an assistant turn."""

    schema_version: str
    data: dict[str, JsonValue]


@dataclass(frozen=True, slots=True)
class ConversationMessage:
    message_id: str
    conversation_id: str
    role: ConversationRole
    content: str
    created_at: datetime
    assistant_payload: AssistantMessagePayload | None = None


@dataclass(frozen=True, slots=True)
class Conversation:
    conversation_id: str
    created_at: datetime
    updated_at: datetime
    messages: tuple[ConversationMessage, ...] = ()


@dataclass(frozen=True, slots=True)
class ConversationSummary:
    conversation_id: str
    created_at: datetime
    updated_at: datetime
    preview: str


def conversation_preview(messages: tuple[ConversationMessage, ...]) -> str:
    """Return a bounded preview from the first user turn only."""
    for message in messages:
        if message.role is ConversationRole.USER:
            return message.content[:120]
    return ""
