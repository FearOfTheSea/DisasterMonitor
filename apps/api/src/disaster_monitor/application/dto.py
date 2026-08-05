"""Application-layer request and response types."""

from dataclasses import dataclass
from datetime import datetime

from disaster_monitor.application.disaster import (
    ReportSection,
    SelectedEventSummary,
    SourceReference,
)


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
class AssistantAnswer:
    """Stable response returned to the HTTP boundary."""

    message: str
    conversation_id: str
    model: str
    response_type: str = "assistant"
    selected_event: SelectedEventSummary | None = None
    retrieval_time: datetime | None = None
    sources: tuple[SourceReference, ...] = ()
    warnings: tuple[str, ...] = ()
    sections: tuple[ReportSection, ...] = ()
    partial: bool = False
