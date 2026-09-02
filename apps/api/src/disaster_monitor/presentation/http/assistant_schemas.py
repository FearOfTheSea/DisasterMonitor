"""HTTP request and response schemas."""

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from disaster_monitor.domain.disaster import (
    Disaster,
)
from disaster_monitor.presentation.http.event_schemas import (
    InvestigationCaseResponse,
    SelectedEventResponse,
    SourceResponse,
)
from disaster_monitor.presentation.http.multimodal_schemas import (
    CommonOperationalPictureResponse,
    MultimodalAssetRequest,
    MultimodalStateResponse,
)
from disaster_monitor.presentation.http.operational_schemas import ReportSectionResponse


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


class MapNavigationActionResponse(BaseModel):
    """One validated viewport-only action requested by the assistant."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["fit_bounds"] = "fit_bounds"
    bounds: tuple[float, float, float, float]
    label: Annotated[str, Field(min_length=1, max_length=160)]
    max_zoom: Annotated[float, Field(ge=2, le=18)] = 10


class OpenPanelOperatorActionResponse(BaseModel):
    """One bounded automatic panel-navigation action."""

    model_config = ConfigDict(extra="forbid")

    action_id: str
    action_type: Literal["open_panel"]
    risk: Literal["automatic"]
    operation: Literal["open"]
    target: Literal["panel"]
    value: Literal["findings", "sources", "watches", "operations"]
    label: Annotated[str, Field(min_length=1, max_length=160)]


class SetTimeWindowOperatorActionResponse(BaseModel):
    """One bounded automatic display-time action."""

    model_config = ConfigDict(extra="forbid")

    action_id: str
    action_type: Literal["set_time_window"]
    risk: Literal["automatic"]
    operation: Literal["set"]
    target: Literal["time_window"]
    value: Literal["1h", "6h", "24h", "48h", "7d"]
    label: Annotated[str, Field(min_length=1, max_length=160)]


class ShowLayerOperatorActionResponse(BaseModel):
    """One bounded automatic map-layer visibility action."""

    model_config = ConfigDict(extra="forbid")

    action_id: str
    action_type: Literal["show_layer"]
    risk: Literal["automatic"]
    operation: Literal["show"]
    target: Literal["map_layer"]
    value: Literal[
        "active-incidents",
        "satellite-imagery",
        "cop-evidence",
        "cyclone-supplemental",
        "authoritative-weather-alerts",
        "compound-correlations",
    ]
    label: Annotated[str, Field(min_length=1, max_length=160)]


class OperatorActionScopeResponse(BaseModel):
    """Canonical scope resolved by application policy for a watch proposal."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["country", "worldwide"]
    country_code: str | None = None
    country_name: str | None = None


class CreateIncidentWatchOperatorActionResponse(BaseModel):
    """One persistent Incident Watch proposal awaiting explicit confirmation."""

    model_config = ConfigDict(extra="forbid")

    action_id: str
    action_type: Literal["create_incident_watch"]
    risk: Literal["confirmation_required"]
    disaster: Disaster
    scope: OperatorActionScopeResponse
    refresh_interval_seconds: Literal[900, 1800, 3600, 21600, 86400]
    label: Annotated[str, Field(min_length=1, max_length=200)]


AssistantOperatorActionResponse = Annotated[
    OpenPanelOperatorActionResponse
    | SetTimeWindowOperatorActionResponse
    | ShowLayerOperatorActionResponse
    | CreateIncidentWatchOperatorActionResponse,
    Field(discriminator="action_type"),
]


class AssistantResponse(BaseModel):
    """Stable assistant response returned to the frontend."""

    message: str
    conversation_id: str
    model: str
    map_action: MapNavigationActionResponse | None = None
    response_type: str = "assistant"
    selected_event: "SelectedEventResponse | None" = None
    retrieval_time: datetime | None = None
    sources: list["SourceResponse"] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    sections: list["ReportSectionResponse"] = Field(default_factory=list)
    partial: bool = False
    investigation: "InvestigationResponse | None" = None
    investigation_case: "InvestigationCaseResponse | None" = None
    decision_support: "DecisionSupportResponse | None" = None
    multimodal: MultimodalStateResponse | None = None
    common_operational_picture: CommonOperationalPictureResponse | None = None
    media_gallery: "DisasterMediaGalleryResponse | None" = None
    operator_actions: list[AssistantOperatorActionResponse] = Field(
        default_factory=list
    )


class ConversationMessageResponse(BaseModel):
    """Persisted turn with optional structured assistant response state."""

    id: str
    role: Literal["user", "assistant"]
    content: str
    created_at: datetime
    assistant_response: AssistantResponse | None = None


class ConversationSummaryResponse(BaseModel):
    """Bounded metadata used by the conversation picker."""

    conversation_id: str
    created_at: datetime
    updated_at: datetime
    preview: str


class ConversationResponse(BaseModel):
    """A durable conversation and its chronological text transcript."""

    conversation_id: str
    created_at: datetime
    updated_at: datetime
    messages: list[ConversationMessageResponse] = Field(default_factory=list)


class DisasterMediaItemResponse(BaseModel):
    media_id: str
    image_url: str
    event_id: str
    physical_event_id: str
    source_id: str
    publisher: str
    source_page_url: str
    caption: str
    credit: str
    credit_kind: str
    published_at: datetime
    captured_at: datetime | None = None
    license_name: str | None = None
    license_url: str | None = None
    rights_status: str
    role: str
    association_status: str
    association_rule_ids: list[str] = Field(default_factory=list)
    association_detail: str
    uncertainty: str
    content_sha256: str
    width: int
    height: int


class DisasterMediaGalleryResponse(BaseModel):
    event_id: str
    physical_event_id: str
    generated_at: datetime
    items: list[DisasterMediaItemResponse] = Field(default_factory=list)
    rejected_count: int = 0
    provider_ids: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class InvestigationResponse(BaseModel):
    """Inspectable agent actions without prompts, reasoning, or raw payloads."""

    status: str
    task_summary: str
    disaster: str | None = None
    country: str | None = None
    information_needs: list[str] = Field(default_factory=list)
    output_modalities: list[str] = Field(default_factory=list)
    actions: list[str] = Field(default_factory=list)
    source_ids: list[str] = Field(default_factory=list)
    evidence_count: int = 0
    capability_gaps: list[str] = Field(default_factory=list)
    termination_reason: str
    geographic_scope: str = "country"
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
    coordination_analytical_release_id: str | None = None
    physical_event_id: str | None = None
    evidence_state_version: str | None = None
    specialist_model_call_count: int = 0
    specialist_fallback_reason: str | None = None
    specialist_provenance_validation_failures: int = 0
    specialist_latency_ms: float = 0.0


class DecisionFactResponse(BaseModel):
    """One source observation with machine-readable epistemic status."""

    fact_id: str
    statement: str
    evidence_ids: list[str]
    source_ids: list[str]
    status: str
    statement_type: str


class DecisionEstimateResponse(BaseModel):
    """One DM-generated inferred estimate, distinct from source estimates."""

    estimate_id: str
    proposition: str
    probability: float
    supporting_evidence_ids: list[str]
    contradicting_evidence_ids: list[str]
    uncertain_evidence_ids: list[str]
    rationale_rule_ids: list[str]
    statement_type: str


class DecisionSupportResponse(BaseModel):
    """Bounded decision artifact safe for typed browser presentation."""

    artifact_id: str
    evidence_state_version: str
    facts: list[DecisionFactResponse]
    estimates: list[DecisionEstimateResponse]
    scenario_mode: str
    recommendation_status: str
    advisory_only: bool
