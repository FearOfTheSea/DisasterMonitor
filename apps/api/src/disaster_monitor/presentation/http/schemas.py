"""HTTP request and response schemas."""

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from disaster_monitor.domain.operations import OperatorDecision
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


class MapNavigationActionResponse(BaseModel):
    """One validated viewport-only action requested by the assistant."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["fit_bounds"] = "fit_bounds"
    bounds: tuple[float, float, float, float]
    label: Annotated[str, Field(min_length=1, max_length=160)]
    max_zoom: Annotated[float, Field(ge=2, le=18)] = 10


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
    decision_support: "DecisionSupportResponse | None" = None
    multimodal: MultimodalStateResponse | None = None
    common_operational_picture: CommonOperationalPictureResponse | None = None
    media_gallery: "DisasterMediaGalleryResponse | None" = None


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
    hazard: str | None = None
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


class SourceResponse(BaseModel):
    """Source metadata exposed to the browser."""

    source_id: str
    publisher: str
    title: str
    canonical_url: str
    published_at: datetime | None = None
    updated_at: datetime | None = None
    retrieved_at: datetime
    snapshot_id: str | None = None


class EventCoordinateResponse(BaseModel):
    """Source-backed WGS84 event coordinate."""

    latitude: Annotated[float, Field(ge=-90, le=90)]
    longitude: Annotated[float, Field(ge=-180, le=180)]


class EventGeometryResponse(BaseModel):
    """Typed event geometry without inferred representative coordinates."""

    kind: Literal["point", "area", "track", "descriptive"]
    coordinates: list[EventCoordinateResponse] = Field(default_factory=list)
    description: str | None = None
    source_id: str


class EventMeasurementResponse(BaseModel):
    """Hazard-neutral event measurement."""

    name: str
    value: float | str
    unit: str | None = None


class SelectedEventResponse(BaseModel):
    """The specific event covered by a current-disaster report."""

    event_id: str
    hazard: str
    location: str
    event_time: datetime
    geometry: EventGeometryResponse | None = None
    measurements: list[EventMeasurementResponse] = Field(default_factory=list)
    source: SourceResponse
    provider_ids: list[str] = Field(default_factory=list)
    geography_status: str


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


class ProviderFreshnessResponse(BaseModel):
    """Operator-safe source freshness without credentials or raw payloads."""

    source_id: str
    state: str
    last_attempt_at: datetime | None = None
    last_success_at: datetime | None = None
    effective_at: datetime | None = None
    age_seconds: int | None = None
    expected_freshness_seconds: int
    consecutive_failures: int
    latest_error_code: str | None = None


class CountryCatalogSourceResponse(BaseModel):
    """Immutable upstream revision admitted to the active catalog."""

    source_id: str
    version: str
    revision: str
    sha256: str


class CountryCatalogUpdateResponse(BaseModel):
    """Current autonomous update and monthly scheduling status."""

    state: Literal["never_run", "running", "updated", "unchanged", "failed"]
    active_version: str
    country_count: int
    automatic_updates_enabled: bool
    trigger: Literal["manual", "scheduled", "script"] | None = None
    last_attempt_at: datetime | None = None
    last_success_at: datetime | None = None
    next_scheduled_at: datetime | None = None
    message: str
    failure_code: str | None = None
    sources: list[CountryCatalogSourceResponse] = Field(default_factory=list)


class EvidenceSnapshotResponse(BaseModel):
    """Immutable evidence metadata; blob locations remain server-private."""

    snapshot_id: str
    source_id: str
    provider_revision: str
    retrieved_at: datetime
    published_at: datetime | None = None
    observed_at: datetime | None = None
    effective_at: datetime
    content_type: str
    payload_sha256: str
    payload_size_bytes: int
    rights_id: str
    content_available: bool
    content_deleted_at: datetime | None = None
    content_deletion_reason: str | None = None


class OperatorActionRequest(BaseModel):
    """A bounded review record, not permission for an external action."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    state_version: Annotated[str, Field(min_length=1, max_length=200)]
    decision: OperatorDecision
    rationale: Annotated[str, Field(min_length=1, max_length=2_000)]
    evidence_ids: Annotated[list[str], Field(max_length=100)] = Field(
        default_factory=list
    )
    policy_ids: Annotated[list[str], Field(max_length=100)] = Field(
        default_factory=list
    )


class OperatorActionResponse(BaseModel):
    """Identity of the attributable review stored by the server."""

    action_id: str
    operator_id: str
    state_version: str
    decision: OperatorDecision
    reviewed_at: datetime
    created: bool
