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
from disaster_monitor.presentation.http.operational_schemas import (
    ReportSectionResponse,
)


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
