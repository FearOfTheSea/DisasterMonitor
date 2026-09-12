"""Transport schemas for the Ground view workflow."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from disaster_monitor.domain.imagery.observations import Sensor


class GroundImageryCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    incident_id: str = Field(min_length=1, max_length=200)
    reference_time: datetime | None = None
    sensors: list[Sensor] = Field(
        default_factory=lambda: [Sensor.SENTINEL_1, Sensor.SENTINEL_2],
        min_length=1,
        max_length=2,
    )
    region: dict[str, Any] | None = None
    context_margin_km: float | None = Field(default=None, ge=0, le=20)
    fallback_radius_km: float | None = Field(default=None, gt=0, le=200)
    onset_earliest: datetime | None = None
    onset_latest: datetime | None = None
    onset_source_id: str | None = Field(default=None, min_length=1, max_length=200)
    owner_scope: str = Field(default="local", min_length=1, max_length=200)
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=200)


class GroundImageryRegionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    region: dict[str, Any]
    context_margin_km: float | None = Field(default=None, ge=0, le=20)


class GroundImagerySelectionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    sensor: Sensor
    role: str = Field(min_length=1, max_length=80)
    observation_id: str = Field(min_length=1, max_length=300)


class GroundImageryPrepareRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    sensor: Sensor
    role: str = Field(min_length=1, max_length=80)
    overview: bool = True
    output_kind: str | None = Field(default=None, min_length=1, max_length=100)


class GroundImageryWatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool
    interval_seconds: int | None = Field(default=None, ge=3_600, le=86_400)


class GroundImageryReadinessResponse(BaseModel):
    state: str
    detail: str


class GroundImageryRegionResponse(BaseModel):
    region_id: str
    version: int
    geometry_hash: str
    association: str
    core: dict[str, Any]
    inspection: dict[str, Any]
    source_footprints: list[dict[str, Any]]


class GroundImageryRegionResolutionResponse(BaseModel):
    state: Literal["resolved", "ambiguous", "needs_region"]
    region: GroundImageryRegionResponse | None
    alternatives: list[dict[str, Any]] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    reason_code: str | None = None


class GroundImageryTimeWindowResponse(BaseModel):
    role: str
    sensor: Sensor
    start: datetime
    end: datetime
    expanded_start: datetime
    expanded_end: datetime


class GroundImageryTemporalPlanResponse(BaseModel):
    policy_version: str
    reference_time: datetime
    impact_start_earliest: datetime | None
    impact_start_latest: datetime | None
    onset_precision: str | None
    onset_source_id: str | None
    windows: list[GroundImageryTimeWindowResponse]


class GroundImageryQualityResponse(BaseModel):
    covered_fraction: float
    usable_fraction: float
    obscured_fraction: float
    uncertain_fraction: float
    uncovered_fraction: float
    component_usable_fractions: dict[str, float]
    quality_state: str
    mask_definition: str


class GroundImageryObservationResponse(BaseModel):
    observation_id: str
    sensor: Sensor
    product_id: str
    acquisition_id: str | None
    revision: str | None
    platform: str | None
    captured_start: datetime
    captured_end: datetime
    readiness: str
    footprint: dict[str, Any]
    mode: str | None
    relative_orbit: int | None
    orbit_direction: str | None
    polarizations: list[str]
    cloud_cover_fraction: float | None
    quality: GroundImageryQualityResponse | None
    source_url: str | None


class GroundImagerySelectionResponse(BaseModel):
    selection_id: str
    sensor: Sensor
    role: str
    label: str
    observation: GroundImageryObservationResponse | None
    reason: str
    explanation: str
    age_class: str | None
    alternative_observation_ids: list[str]


class GroundImageryGridResponse(BaseModel):
    crs: str
    min_x: float
    min_y: float
    max_x: float
    max_y: float
    pixel_size_m: float
    width: int
    height: int
    resolution_label: str


class GroundImageryArtifactResponse(BaseModel):
    artifact_id: str
    selection_id: str
    sensor: Sensor
    role: str
    output_kind: str
    content_type: str
    storage_key: str
    byte_count: int
    sha256: str
    source_product_ids: list[str]
    grid: GroundImageryGridResponse
    created_at: datetime


class GroundImagerySensorStatusResponse(BaseModel):
    sensor: Sensor
    scanned_count: int
    scan_complete: bool
    next_cursor: str | None
    failure_code: str | None
    failure_detail: str | None
    selections: list[GroundImagerySelectionResponse]


class GroundImageryRequestResponse(BaseModel):
    request_id: str
    request_version: int
    incident_id: str
    disaster: str
    state: str
    reason_codes: list[str]
    reference_time: datetime
    region: GroundImageryRegionResolutionResponse
    temporal_plan: GroundImageryTemporalPlanResponse
    sensors: list[GroundImagerySensorStatusResponse]
    next_check_at: datetime | None = None
    watch_enabled: bool = False
    watch_interval_seconds: int | None = None
    artifacts: list[GroundImageryArtifactResponse] = Field(default_factory=list)


class GroundImageryObservationPageResponse(BaseModel):
    observations: list[GroundImageryObservationResponse]
    next_cursor: str | None
    total: int


class GroundImageryManifestResponse(BaseModel):
    manifest_version: str
    request_id: str
    request_version: int
    incident_id: str
    disaster: str
    region: dict[str, Any] | None
    temporal_policy_version: str
    reference_time: str
    onset: dict[str, Any] | None
    state: str
    reason_codes: list[str]
    observations: list[dict[str, Any]]
    selections: list[dict[str, Any]]
    artifacts: list[dict[str, Any]] = Field(default_factory=list)
