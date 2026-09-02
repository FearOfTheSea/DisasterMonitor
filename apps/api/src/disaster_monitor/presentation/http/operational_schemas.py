"""HTTP request and response schemas."""

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from disaster_monitor.domain.disaster import (
    Disaster,
)
from disaster_monitor.domain.operations import OperatorDecision


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
