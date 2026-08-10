"""HTTP request and response schemas."""

from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

from disaster_monitor.presentation.http.multimodal_schemas import (
    CommonOperationalPictureResponse,
    MultimodalAssetRequest,
    MultimodalStateResponse,
)


class MapViewRequest(BaseModel):
    """Optional current browser map view."""

    model_config = ConfigDict(extra="forbid")

    center_latitude: Annotated[float, Field(ge=-90, le=90)]
    center_longitude: Annotated[float, Field(ge=-180, le=180)]
    zoom: Annotated[float, Field(ge=0, le=24)]


class AssistantRequest(BaseModel):
    """Assistant request accepted by the public API."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    question: Annotated[str, Field(min_length=1, max_length=2_000)]
    conversation_id: Annotated[str | None, Field(max_length=100)] = None
    map_view: MapViewRequest | None = None
    multimodal_assets: Annotated[list[MultimodalAssetRequest], Field(max_length=3)] = (
        Field(default_factory=list)
    )


class AssistantResponse(BaseModel):
    """Stable assistant response returned to the frontend."""

    message: str
    conversation_id: str
    model: str
    response_type: str = "assistant"
    selected_event: "SelectedEventResponse | None" = None
    retrieval_time: datetime | None = None
    sources: list["SourceResponse"] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    sections: list["ReportSectionResponse"] = Field(default_factory=list)
    partial: bool = False
    investigation: "InvestigationResponse | None" = None
    multimodal: MultimodalStateResponse | None = None
    common_operational_picture: CommonOperationalPictureResponse | None = None


class InvestigationResponse(BaseModel):
    """Inspectable agent actions without prompts, reasoning, or raw payloads."""

    status: str
    task_summary: str
    hazard: str | None = None
    country: str | None = None
    information_needs: list[str] = Field(default_factory=list)
    output_modalities: list[str] = Field(default_factory=list)
    actions: list[str] = Field(default_factory=list)
    source_ids: list[str] = Field(default_factory=list)
    evidence_count: int = 0
    capability_gaps: list[str] = Field(default_factory=list)
    termination_reason: str
    triage_priority: str | None = None
    triage_score: int | None = None
    triage_action: str | None = None
    triage_autonomy_mode: str | None = None
    triage_requires_human_intervention: bool | None = None
    decision_action: str | None = None
    decision_autonomy_mode: str | None = None
    decision_requires_human_intervention: bool | None = None
    decision_termination_reason: str | None = None
    decision_state_revision: int | None = None
    decision_active_internal_states: list[str] = Field(default_factory=list)
    specialist_handoff_count: int = 0
    specialist_roles: list[str] = Field(default_factory=list)
    collaboration_status: str | None = None
    collaboration_finding_count: int = 0
    collaboration_deadlock_count: int = 0
    collaboration_iterations: int | None = None
    collaboration_fallback_reason: str | None = None
    coordination_supervision_id: str | None = None
    coordination_supervisor_status: str | None = None
    coordination_sufficient: bool | None = None
    coordination_required_finding_keys: list[str] = Field(default_factory=list)
    coordination_missing_finding_keys: list[str] = Field(default_factory=list)
    coordination_termination_reason: str | None = None
    coordination_final_rationale: str | None = None
    coordination_evidence_ids: list[str] = Field(default_factory=list)
    coordination_analytical_focus: str | None = None
    coordination_analytical_parameter_set_id: str | None = None


class SourceResponse(BaseModel):
    """Source metadata exposed to the browser."""

    source_id: str
    publisher: str
    title: str
    canonical_url: str
    published_at: datetime | None = None
    updated_at: datetime | None = None
    retrieved_at: datetime


class SelectedEventResponse(BaseModel):
    """The specific event covered by a current-disaster report."""

    event_id: str
    hazard: str
    location: str
    event_time: datetime
    magnitude: float | None = None
    intensity: str | None = None
    depth_km: float | None = None
    source: SourceResponse
    provider_ids: list[str] = Field(default_factory=list)


class ReportSectionResponse(BaseModel):
    """One readable report section."""

    title: str
    content: str


class HealthResponse(BaseModel):
    """Liveness response."""

    status: str
    service: str
    version: str


class ReadinessResponse(BaseModel):
    """Local-model readiness response."""

    status: str
    ollama_available: bool
    model_available: bool
    model: str
