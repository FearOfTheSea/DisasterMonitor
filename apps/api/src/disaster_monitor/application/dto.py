"""Application-layer request and response types."""

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class ModelMessage:
    """Provider-neutral chat message."""

    role: str
    content: str


@dataclass(frozen=True, slots=True)
class ModelRequest:
    """Provider-neutral model invocation request."""

    messages: tuple[ModelMessage, ...]


@dataclass(frozen=True, slots=True)
class ModelResponse:
    """Provider-neutral model invocation response."""

    text: str
    model: str


@dataclass(frozen=True, slots=True)
class ModelReadiness:
    """Availability of the local model service and configured model."""

    ollama_available: bool
    model_available: bool
    model: str


@dataclass(frozen=True, slots=True)
class DisasterInformationItem:
    """One time-stamped report returned by a current-information provider."""

    title: str
    source: str
    published_at: datetime | None
    url: str
    summary: str


@dataclass(frozen=True, slots=True)
class DisasterInformationResult:
    """Current disaster reports and the time at which they were retrieved."""

    query: str
    retrieved_at: datetime
    items: tuple[DisasterInformationItem, ...]


@dataclass(frozen=True, slots=True)
class AssistantAnswer:
    """Stable response returned to the HTTP boundary."""

    message: str
    conversation_id: str
    model: str
