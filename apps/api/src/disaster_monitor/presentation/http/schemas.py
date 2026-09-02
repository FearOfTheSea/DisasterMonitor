"""HTTP request and response schemas."""

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from disaster_monitor.domain.disaster import (
    Disaster,
    MeasurementKind,
    ProviderTier,
    SourceAuthority,
)
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
    estimated: bool = False


class EventMeasurementResponse(BaseModel):
    """Disaster-neutral event measurement."""

    kind: MeasurementKind
    value: float | str
    unit: str | None = None
    source_id: str


class CycloneMapCoordinateResponse(BaseModel):
    """Exact WGS84 coordinate from a supplemental cyclone product."""

    latitude: Annotated[float, Field(ge=-90, le=90)]
    longitude: Annotated[float, Field(ge=-180, le=180)]
    valid_at: datetime | None = None


class CycloneMapLayerResponse(BaseModel):
    """Explicitly typed cyclone geometry separate from event occurrence."""

    layer_id: str
    semantic_role: Literal[
        "provisional_track", "forecast_track", "uncertainty_area", "wind_radii"
    ]
    geometry_kind: Literal["point", "track", "area"]
    coordinates: list[CycloneMapCoordinateResponse]
    source: SourceResponse
    issued_at: datetime
    valid_from: datetime | None = None
    valid_to: datetime | None = None
    storm_id: str
    provisional: bool
    limitation: str
    reconciliation: str
    wind_threshold: float | None = None
    wind_threshold_unit: str | None = None


class SelectedEventResponse(BaseModel):
    """The specific event covered by a current-disaster report."""

    event_id: str
    disaster: str
    location: str
    event_time: datetime
    geometry: EventGeometryResponse | None = None
    measurements: list[EventMeasurementResponse] = Field(default_factory=list)
    source: SourceResponse
    provider_ids: list[str] = Field(default_factory=list)
    geography_status: str
    supplemental_geometry: list[CycloneMapLayerResponse] = Field(default_factory=list)


class ActiveIncidentResponse(BaseModel):
    """One worldwide event with exact provider evidence and authority."""

    event_id: str
    physical_event_id: str | None = None
    disaster: Disaster
    location: str
    event_time: datetime
    geometry: EventGeometryResponse | None = None
    measurements: list[EventMeasurementResponse] = Field(default_factory=list)
    provider_ids: list[str] = Field(default_factory=list)
    provider_tier: ProviderTier
    source_authority: SourceAuthority
    source: SourceResponse


class CompoundHazardCorrelationResponse(BaseModel):
    """One bounded descriptive association between incidents in this snapshot."""

    correlation_id: str
    rule_id: str
    relationship: Literal["spatiotemporal_association"]
    first_event_id: str
    first_physical_event_id: str | None = None
    first_disaster: Disaster
    second_event_id: str
    second_physical_event_id: str | None = None
    second_disaster: Disaster
    distance_km: Annotated[float, Field(ge=0)]
    time_delta_seconds: Annotated[int, Field(ge=0)]
    source_ids: list[str] = Field(default_factory=list)
    summary: str
    limitation: str


class InvestigationCaseCountryResponse(BaseModel):
    country_code: str
    country_name: str


class CrossHazardAssessmentResponse(BaseModel):
    status: Literal[
        "associated",
        "not_established",
        "unsupported_pair",
        "insufficient_evidence",
    ]
    summary: str
    limitation: str


class InvestigationTargetResponse(BaseModel):
    """One bounded branch safe for browser rendering."""

    target_id: str
    disaster: Disaster
    status: Literal["completed", "partial", "coverage_unavailable", "failed"]
    selected_event: "SelectedEventResponse | None" = None
    sources: list["SourceResponse"] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    sections: list["ReportSectionResponse"] = Field(default_factory=list)
    partial: bool
    termination_reason: str


class InvestigationCaseResponse(BaseModel):
    """User-safe result of one bounded two-hazard investigation."""

    case_id: str
    country: InvestigationCaseCountryResponse
    status: Literal["completed", "partial"]
    partial: bool
    targets: list[InvestigationTargetResponse] = Field(min_length=2, max_length=2)
    cross_hazard_assessment: CrossHazardAssessmentResponse
    correlations: list[CompoundHazardCorrelationResponse] = Field(default_factory=list)


class DisasterIncidentCoverageResponse(BaseModel):
    """Honest provider outcome for one supported disaster."""

    disaster: Disaster
    state: Literal["events_found", "no_matching_records", "degraded", "unavailable"]
    incident_count: int
    providers: list[str] = Field(default_factory=list)
    detail: str


class ActiveIncidentsSnapshotResponse(BaseModel):
    """Bounded all-hazard discovery result for the monitoring surface."""

    retrieved_at: datetime
    incidents: list[ActiveIncidentResponse] = Field(default_factory=list)
    coverage: list[DisasterIncidentCoverageResponse] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    correlations: list[CompoundHazardCorrelationResponse] = Field(default_factory=list)


class CountryIncidentWatchScopeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    kind: Literal["country"]
    country: Annotated[str, Field(min_length=1, max_length=200)]


class WorldwideIncidentWatchScopeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["worldwide"]


class IncidentWatchCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    disaster: Disaster
    scope: Annotated[
        CountryIncidentWatchScopeRequest | WorldwideIncidentWatchScopeRequest,
        Field(discriminator="kind"),
    ]
    refresh_interval_seconds: Annotated[int, Field(ge=300, le=86_400)]


class IncidentWatchScopeResponse(BaseModel):
    kind: Literal["country", "worldwide"]
    country_code: str | None
    country_name: str | None


class IncidentWatchResponse(BaseModel):
    watch_id: str
    disaster: Disaster
    scope: IncidentWatchScopeResponse
    enabled: bool
    refresh_interval_seconds: int
    created_at: datetime
    updated_at: datetime
    next_refresh_at: datetime
    last_checked_at: datetime | None
    coverage_state: (
        Literal[
            "events_found",
            "no_matching_records",
            "stale",
            "degraded",
            "unavailable",
        ]
        | None
    )
    unread_change_count: int


class IncidentWatchEnabledRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool


class IncidentWatchEventResponse(BaseModel):
    physical_event_id: str
    event_id: str
    disaster: Disaster
    location: str
    event_time: datetime
    geometry: EventGeometryResponse | None
    measurements: list[EventMeasurementResponse] = Field(default_factory=list)
    provider_ids: list[str] = Field(default_factory=list)
    provider_tier: ProviderTier
    source_authority: SourceAuthority
    source: SourceResponse
    evidence_sources: list[SourceResponse] = Field(default_factory=list)


class IncidentWatchChangeResponse(BaseModel):
    change_id: str
    watch_id: str
    kind: Literal[
        "new_event",
        "observation_gap",
        "measurements_changed",
        "geometry_changed",
        "evidence_set_changed",
        "coverage_changed",
    ]
    summary: str
    detail: str
    created_at: datetime
    read_at: datetime | None
    source_ids: list[str] = Field(default_factory=list)
    observation_id: str
    previous_observation_id: str | None
    before_hash: str | None
    after_hash: str | None
    incident: IncidentWatchEventResponse | None


class IncidentWatchMarkReadRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    change_ids: Annotated[list[str], Field(max_length=500)] = Field(
        default_factory=list
    )


class IncidentWatchMarkReadResponse(BaseModel):
    watch_id: str
    marked_read_count: int
    unread_change_count: int


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


class SatelliteImageryProductResponse(BaseModel):
    """Credential-free capabilities for one map imagery source."""

    source_id: str
    display_name: str
    provider_id: str
    provider_name: str
    temporal_mode: Literal["daily", "subdaily", "fixed"]
    temporal_step_minutes: int | None = None
    attribution: str
    maximum_useful_zoom: int
    access_mode: Literal["direct_gibs", "api"]
    available: bool


class SatelliteImageryCatalogResponse(BaseModel):
    """Selectable satellite sources without upstream addresses or secrets."""

    products: list[SatelliteImageryProductResponse]


class SourceOperationalStateResponse(BaseModel):
    """Credential-free executable state kept separate from maintained metadata."""

    registered: bool
    configured: bool
    availability: Literal["available", "unconfigured", "maintained_only"]
    availability_detail: str
    provider_tier: Literal["primary", "secondary"] | None = None
    execution_roles: list[str] = Field(default_factory=list)


class SourceCatalogItemResponse(BaseModel):
    source_id: str
    provider: str
    publisher: str
    authority: str
    information_roles: list[str] = Field(default_factory=list)
    supported_disasters: list[Disaster] = Field(default_factory=list)
    geographic_scopes: list[Literal["country", "worldwide"]] = Field(
        default_factory=list
    )
    country_codes: list[str] | None = None
    coverage_description: str
    documentation_path: str | None = None
    freshness_semantics: str
    stale_threshold_seconds: int | None = None
    attribution: str
    limitations: list[str] = Field(default_factory=list)
    operational_state: SourceOperationalStateResponse


class SourceCatalogResponse(BaseModel):
    catalog_version: str
    sources: list[SourceCatalogItemResponse] = Field(default_factory=list)


class WeatherAlertCoordinateResponse(BaseModel):
    latitude: Annotated[float, Field(ge=-90, le=90)]
    longitude: Annotated[float, Field(ge=-180, le=180)]


class WeatherAlertGeometryResponse(BaseModel):
    kind: Literal["polygon"] = "polygon"
    rings: list[list[WeatherAlertCoordinateResponse]] = Field(default_factory=list)


class WeatherAlertResponse(BaseModel):
    provider_alert_id: str
    source_id: str
    publisher: str
    event: str
    headline: str | None = None
    severity: Literal["extreme", "severe", "moderate", "minor", "unknown"]
    urgency: Literal["immediate", "expected", "future", "past", "unknown"]
    certainty: Literal["observed", "likely", "possible", "unlikely", "unknown"]
    sent: datetime | None = None
    effective: datetime | None = None
    onset: datetime | None = None
    expires: datetime | None = None
    affected_area: str
    geometry: WeatherAlertGeometryResponse | None = None
    canonical_url: str | None = None
    retrieved_at: datetime
    attribution: str
    limitations: list[str] = Field(default_factory=list)


class WeatherAlertCoverageResponse(BaseModel):
    source_id: str
    publisher: str
    state: Literal["alerts_found", "no_active_alerts", "degraded", "unavailable"]
    detail: str
    geographic_scope: str
    limitations: list[str] = Field(default_factory=list)


class WeatherAlertWarningResponse(BaseModel):
    reason_code: str
    detail: str
    retryable: bool
    partial: bool


class WeatherAlertsSnapshotResponse(BaseModel):
    retrieved_at: datetime
    alerts: list[WeatherAlertResponse] = Field(default_factory=list)
    coverage: WeatherAlertCoverageResponse
    warnings: list[WeatherAlertWarningResponse] = Field(default_factory=list)


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
