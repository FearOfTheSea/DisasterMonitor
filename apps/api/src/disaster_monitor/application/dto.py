"""Application-layer request and response types."""

from dataclasses import dataclass
from datetime import datetime

from disaster_monitor.application.disaster import ReportSection, SelectedEventSummary
from disaster_monitor.domain.disaster import SourceReference
from disaster_monitor.domain.multimodal import (
    CommonOperationalPicture,
    MultimodalEvidenceState,
)


@dataclass(frozen=True, slots=True)
class InvestigationSummary:
    """User-safe agent activity; never model reasoning or raw payloads."""

    status: str
    task_summary: str
    hazard: str | None
    country: str | None
    information_needs: tuple[str, ...]
    output_modalities: tuple[str, ...]
    actions: tuple[str, ...]
    source_ids: tuple[str, ...]
    evidence_count: int
    capability_gaps: tuple[str, ...]
    termination_reason: str
    triage_priority: str | None = None
    triage_score: int | None = None
    triage_action: str | None = None
    triage_autonomy_mode: str | None = None
    triage_requires_human_intervention: bool | None = None


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
    investigation: InvestigationSummary | None = None
    multimodal_state: MultimodalEvidenceState | None = None
    common_operational_picture: CommonOperationalPicture | None = None
