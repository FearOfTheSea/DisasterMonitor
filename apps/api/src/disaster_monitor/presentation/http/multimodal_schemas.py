"""Typed HTTP schemas for bounded multimodal inputs and COP outputs."""

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from disaster_monitor.domain.disaster import Hazard
from disaster_monitor.domain.multimodal import CaptureRole


class FootprintRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    crs: Literal["EPSG:4326"] = "EPSG:4326"
    coordinates: Annotated[
        list[list[tuple[float, float]]], Field(min_length=1, max_length=8)
    ]


class MultimodalAssetRequest(BaseModel):
    """Bounded inline bytes; no filesystem path or fetchable endpoint is accepted."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    content_base64: Annotated[str, Field(min_length=1, max_length=6_700_000)]
    attribution: Annotated[str, Field(min_length=1, max_length=500)]
    captured_at: datetime | None = None
    footprint: FootprintRequest | None = None
    declared_hazard: Hazard | None = None
    declared_country_code: Annotated[str | None, Field(pattern=r"^[A-Za-z]{3}$")] = None
    capture_role: CaptureRole = CaptureRole.UNKNOWN
    canonical_url: Annotated[str | None, Field(max_length=2_000)] = None
    dataset_id: Annotated[str | None, Field(max_length=200)] = None
    license_name: Annotated[str | None, Field(max_length=200)] = None
    processing_level: Annotated[str | None, Field(max_length=100)] = None
    parent_asset_ids: Annotated[list[str], Field(max_length=8)] = Field(
        default_factory=list
    )
    event_id_hint: Annotated[str | None, Field(max_length=200)] = None


class PointGeometryResponse(BaseModel):
    type: Literal["Point"]
    coordinates: tuple[float, float]
    crs: Literal["EPSG:4326"]


class LineStringGeometryResponse(BaseModel):
    type: Literal["LineString"]
    coordinates: list[tuple[float, float]]
    crs: Literal["EPSG:4326"]


class PolygonGeometryResponse(BaseModel):
    type: Literal["Polygon"]
    coordinates: list[list[tuple[float, float]]]
    crs: Literal["EPSG:4326"]


GeometryResponse = (
    PointGeometryResponse | LineStringGeometryResponse | PolygonGeometryResponse
)


class MultimodalSourceResponse(BaseModel):
    source_id: str
    attribution: str
    canonical_url: str | None = None
    dataset_id: str | None = None
    license_name: str | None = None


class MultimodalAssetResponse(BaseModel):
    asset_id: str
    source: MultimodalSourceResponse
    retrieved_at: datetime
    captured_at: datetime | None = None
    modality: str
    media_type: str
    content_sha256: str
    byte_length: int
    width: int | None = None
    height: int | None = None
    footprint: PolygonGeometryResponse | None = None
    declared_hazard: str | None = None
    declared_country_code: str | None = None
    capture_role: str
    processing_level: str | None = None
    parent_asset_ids: list[str] = Field(default_factory=list)
    event_id_hint: str | None = None
    eligibility: str
    eligibility_reasons: list[str] = Field(default_factory=list)


class AssetEventAssociationResponse(BaseModel):
    association_id: str
    asset_id: str
    physical_event_id: str
    status: str
    geography_match: bool | None = None
    time_match: bool | None = None
    hazard_match: bool | None = None
    country_match: bool | None = None
    event_id_match: bool | None = None
    distance_km: float | None = None
    time_delta_seconds: float | None = None
    rule_ids: list[str] = Field(default_factory=list)
    detail: str


class VisualAnalysisConfigurationResponse(BaseModel):
    model_id: str
    model_digest: str | None = None
    adapter_version: str
    analysis_version: str
    prompt_version: str
    preprocessing_version: str
    maximum_output_tokens: int
    temperature: float
    seed: int


class VisualObservationResponse(BaseModel):
    observation_id: str
    asset_id: str
    association_id: str
    physical_event_id: str
    modality: Literal["image"]
    truth_status: Literal["analytical"]
    kind: str
    status: str
    damage_level: str | None = None
    question: str | None = None
    answer: str | None = None
    answerable: bool | None = None
    confidence: float | None = None
    uncertainty: str
    visual_cues: list[str] = Field(default_factory=list)
    configuration: VisualAnalysisConfigurationResponse
    created_at: datetime
    safety_rule_ids: list[str] = Field(default_factory=list)


class MultimodalStateResponse(BaseModel):
    state_version: str
    evidence_world_state_version: str
    physical_event_id: str
    assets: list[MultimodalAssetResponse] = Field(default_factory=list)
    associations: list[AssetEventAssociationResponse] = Field(default_factory=list)
    observations: list[VisualObservationResponse] = Field(default_factory=list)
    evaluated_at: datetime


class SourceMapFeatureResponse(BaseModel):
    feature_type: Literal["source"]
    feature_id: str
    physical_event_id: str
    source_id: str
    source_asset_ids: list[str]
    created_at: datetime
    updated_at: datetime | None = None
    semantic_kind: str
    geometry: GeometryResponse
    attribution: str
    status: str
    uncertainty: str
    authority: Literal["official_source", "source_supplied"]
    source_authority: Literal["official", "source_supplied"]


class AnalyticalMapFeatureResponse(BaseModel):
    feature_type: Literal["analytical"]
    feature_id: str
    physical_event_id: str
    source_asset_ids: list[str]
    visual_observation_ids: list[str]
    created_at: datetime
    updated_at: datetime | None = None
    semantic_kind: str
    geometry: GeometryResponse
    attribution: str
    status: str
    uncertainty: str
    confidence: float | None = None
    authority: Literal["analytical_generated"]


class SourceMapLayerResponse(BaseModel):
    layer_type: Literal["source"]
    layer_id: str
    physical_event_id: str
    title: str
    semantic_kind: str
    features: list[SourceMapFeatureResponse]
    source_ids: list[str]
    source_asset_ids: list[str]
    created_at: datetime
    updated_at: datetime
    status: str
    uncertainty: str
    attribution: str


class AnalyticalMapLayerResponse(BaseModel):
    layer_type: Literal["analytical"]
    layer_id: str
    physical_event_id: str
    title: str
    semantic_kind: str
    features: list[AnalyticalMapFeatureResponse]
    source_asset_ids: list[str]
    visual_observation_ids: list[str]
    created_at: datetime
    updated_at: datetime
    status: str
    uncertainty: str
    attribution: str


CopLayerResponse = SourceMapLayerResponse | AnalyticalMapLayerResponse


class CommonOperationalPictureResponse(BaseModel):
    cop_id: str
    physical_event_id: str
    multimodal_state_version: str
    created_at: datetime
    updated_at: datetime
    status: str
    layers: list[CopLayerResponse]
