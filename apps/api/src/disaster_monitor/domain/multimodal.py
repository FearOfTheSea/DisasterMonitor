"""Typed multimodal evidence and common-operational-picture artifacts."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from math import isfinite


class AssetModality(StrEnum):
    """Raw media classes accepted by the bounded multimodal boundary."""

    IMAGE = "image"


class CaptureRole(StrEnum):
    """Temporal role asserted by source metadata, never inferred from pixels."""

    PRE_EVENT = "pre_event"
    POST_EVENT = "post_event"
    SINGLE_CAPTURE = "single_capture"
    UNKNOWN = "unknown"


class AssetEligibility(StrEnum):
    """Whether an asset has enough provenance for grounded visual analysis."""

    ANALYSIS_ELIGIBLE = "analysis_eligible"
    PREVIEW_ONLY = "preview_only"
    ORPHANED = "orphaned"
    REJECTED = "rejected"


class EventAssociationStatus(StrEnum):
    """Deterministic relationship between an asset and a physical event."""

    ASSOCIATED = "associated"
    AMBIGUOUS = "ambiguous"
    UNMATCHED = "unmatched"
    ORPHANED = "orphaned"


class VisualObservationKind(StrEnum):
    """Canonical analytical products emitted by visual analysis."""

    DAMAGE_ASSESSMENT = "damage_assessment"
    VISUAL_QUESTION_ANSWER = "visual_question_answer"
    OCR_EXTRACTION = "ocr_extraction"


class DamageLevel(StrEnum):
    """Roadmap-aligned ordinal visible-damage categories."""

    NO_VISIBLE_DAMAGE = "no_visible_damage"
    MINOR_DAMAGE = "minor_damage"
    MAJOR_DAMAGE = "major_damage"
    DESTROYED = "destroyed"
    UNKNOWN = "unknown"


class VisualObservationStatus(StrEnum):
    """Outcome of one bounded analytical request."""

    PRODUCED = "produced"
    ABSTAINED = "abstained"
    RESEARCH_ONLY = "research_only"


class VisualTruthStatus(StrEnum):
    """Epistemic marker that cannot be confused with a reported fact."""

    ANALYTICAL = "analytical"


class GeometryKind(StrEnum):
    POINT = "point"
    LINE_STRING = "line_string"
    POLYGON = "polygon"


class SourceGeometryAuthority(StrEnum):
    """Authority that may only be used by source-supplied map features."""

    OFFICIAL = "official"
    SOURCE_SUPPLIED = "source_supplied"


class MapFeatureAuthority(StrEnum):
    """Machine-readable distinction between source and generated geometry."""

    OFFICIAL_SOURCE = "official_source"
    SOURCE_SUPPLIED = "source_supplied"
    ANALYTICAL_GENERATED = "analytical_generated"


class CopStatus(StrEnum):
    CURRENT = "current"
    STALE = "stale"
    PREVIEW_ONLY = "preview_only"


@dataclass(frozen=True, slots=True)
class GeoPoint:
    """One WGS84 longitude/latitude coordinate."""

    longitude: float
    latitude: float

    def __post_init__(self) -> None:
        if not isfinite(self.longitude) or not isfinite(self.latitude):
            raise ValueError("Coordinates must be finite.")
        if not -180 <= self.longitude <= 180:
            raise ValueError("Longitude must be between -180 and 180.")
        if not -90 <= self.latitude <= 90:
            raise ValueError("Latitude must be between -90 and 90.")


@dataclass(frozen=True, slots=True)
class GeoLineString:
    """Validated coordinate sequence in WGS84."""

    points: tuple[GeoPoint, ...]
    crs: str = "EPSG:4326"
    kind: GeometryKind = field(init=False, default=GeometryKind.LINE_STRING)

    def __post_init__(self) -> None:
        if self.crs != "EPSG:4326":
            raise ValueError("Only explicit EPSG:4326 geometry is supported.")
        if len(self.points) < 2:
            raise ValueError("A line string requires at least two points.")


@dataclass(frozen=True, slots=True)
class GeoPolygon:
    """One WGS84 polygon with a closed exterior and optional closed holes."""

    rings: tuple[tuple[GeoPoint, ...], ...]
    crs: str = "EPSG:4326"
    kind: GeometryKind = field(init=False, default=GeometryKind.POLYGON)

    def __post_init__(self) -> None:
        if self.crs != "EPSG:4326":
            raise ValueError("Only explicit EPSG:4326 geometry is supported.")
        if not self.rings:
            raise ValueError("A polygon requires an exterior ring.")
        for ring in self.rings:
            if len(ring) < 4 or ring[0] != ring[-1]:
                raise ValueError(
                    "Every polygon ring requires at least four closed coordinates."
                )


MapGeometry = GeoPoint | GeoLineString | GeoPolygon


@dataclass(frozen=True, slots=True)
class MultimodalSourceMetadata:
    """Audit metadata for an admitted source asset."""

    source_id: str
    attribution: str
    canonical_url: str | None = None
    dataset_id: str | None = None
    license_name: str | None = None

    def __post_init__(self) -> None:
        if not self.source_id.strip():
            raise ValueError("Multimodal source metadata requires a stable source ID.")
        if not self.attribution.strip():
            raise ValueError("Multimodal source metadata requires attribution text.")
        if self.canonical_url is not None and not self.canonical_url.startswith(
            "https://"
        ):
            raise ValueError("A supplied canonical asset URL must use HTTPS.")


@dataclass(frozen=True, slots=True)
class MultimodalAsset:
    """A raw source asset, kept separate from all AI interpretations."""

    asset_id: str
    source: MultimodalSourceMetadata
    retrieved_at: datetime
    captured_at: datetime | None
    modality: AssetModality
    media_type: str
    content_sha256: str
    byte_length: int
    width: int | None
    height: int | None
    footprint: GeoPolygon | None
    declared_hazard: StrEnum | None
    declared_country_code: str | None
    capture_role: CaptureRole
    processing_level: str | None
    parent_asset_ids: tuple[str, ...]
    event_id_hint: str | None
    eligibility: AssetEligibility
    eligibility_reasons: tuple[str, ...]
    content: bytes = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        if not self.asset_id.strip():
            raise ValueError("A multimodal asset requires a stable asset ID.")
        if len(self.content_sha256) != 64 or any(
            character not in "0123456789abcdef" for character in self.content_sha256
        ):
            raise ValueError("A multimodal asset requires a lowercase SHA-256 hash.")
        if self.byte_length <= 0 or self.byte_length != len(self.content):
            raise ValueError("Asset byte length must match non-empty content.")
        if (self.width is None) != (self.height is None):
            raise ValueError("Image width and height must both be known or unknown.")
        if self.width is not None and (self.width <= 0 or (self.height or 0) <= 0):
            raise ValueError("Image dimensions must be positive.")


@dataclass(frozen=True, slots=True)
class AssetEventAssociation:
    """Auditable, metadata-owned association to one physical event."""

    association_id: str
    asset_id: str
    physical_event_id: str
    status: EventAssociationStatus
    geography_match: bool | None
    time_match: bool | None
    hazard_match: bool | None
    country_match: bool | None
    event_id_match: bool | None
    distance_km: float | None
    time_delta_seconds: float | None
    rule_ids: tuple[str, ...]
    detail: str


@dataclass(frozen=True, slots=True)
class VisualAnalysisConfiguration:
    """Reproducible model, prompt, preprocessing, and decoding identity."""

    model_id: str
    model_digest: str | None
    adapter_version: str
    analysis_version: str
    prompt_version: str
    preprocessing_version: str
    maximum_output_tokens: int
    temperature: float
    seed: int

    def __post_init__(self) -> None:
        if self.maximum_output_tokens <= 0:
            raise ValueError("Visual analysis requires a positive output-token cap.")


@dataclass(frozen=True, slots=True)
class VisualObservation:
    """An AI-derived visual assertion that can never become a ReportedFact."""

    observation_id: str
    asset_id: str
    association_id: str
    physical_event_id: str
    kind: VisualObservationKind
    status: VisualObservationStatus
    damage_level: DamageLevel | None
    question: str | None
    answer: str | None
    answerable: bool | None
    confidence: float | None
    uncertainty: str
    visual_cues: tuple[str, ...]
    configuration: VisualAnalysisConfiguration
    created_at: datetime
    safety_rule_ids: tuple[str, ...] = ()
    truth_status: VisualTruthStatus = VisualTruthStatus.ANALYTICAL

    def __post_init__(self) -> None:
        if not self.asset_id or not self.association_id or not self.physical_event_id:
            raise ValueError("Visual observations require complete artifact lineage.")
        if not self.uncertainty.strip():
            raise ValueError("Visual observations require explicit uncertainty text.")
        if self.confidence is not None and not 0 <= self.confidence <= 1:
            raise ValueError("Visual confidence must be between zero and one.")
        if self.status == VisualObservationStatus.ABSTAINED and self.answerable is True:
            raise ValueError("An abstained visual answer cannot be marked answerable.")
        if (
            self.kind == VisualObservationKind.DAMAGE_ASSESSMENT
            and self.status == VisualObservationStatus.ABSTAINED
            and self.damage_level != DamageLevel.UNKNOWN
        ):
            raise ValueError("An abstained damage assessment must remain unknown.")


@dataclass(frozen=True, slots=True)
class MultimodalEvidenceState:
    """Versioned analytical extension of, not replacement for, EW state."""

    state_version: str
    evidence_world_state_version: str
    physical_event_id: str
    assets: tuple[MultimodalAsset, ...]
    associations: tuple[AssetEventAssociation, ...]
    observations: tuple[VisualObservation, ...]
    evaluated_at: datetime


@dataclass(frozen=True, slots=True)
class SourceMapFeature:
    """Geometry supplied by a named source; never generated by the model."""

    feature_id: str
    physical_event_id: str
    source_id: str
    source_asset_ids: tuple[str, ...]
    created_at: datetime
    updated_at: datetime | None
    semantic_kind: str
    geometry: MapGeometry
    attribution: str
    status: CopStatus
    uncertainty: str
    source_authority: SourceGeometryAuthority
    authority: MapFeatureAuthority = field(init=False)

    def __post_init__(self) -> None:
        authority = (
            MapFeatureAuthority.OFFICIAL_SOURCE
            if self.source_authority == SourceGeometryAuthority.OFFICIAL
            else MapFeatureAuthority.SOURCE_SUPPLIED
        )
        object.__setattr__(self, "authority", authority)
        if not self.source_id.strip() or not self.source_asset_ids:
            raise ValueError("Source map features require source and asset provenance.")
        if not self.attribution.strip() or not self.uncertainty.strip():
            raise ValueError(
                "Source map features require visible attribution and uncertainty."
            )


@dataclass(frozen=True, slots=True)
class AnalyticalMapFeature:
    """Generated analytical geometry that is structurally never official."""

    feature_id: str
    physical_event_id: str
    source_asset_ids: tuple[str, ...]
    visual_observation_ids: tuple[str, ...]
    created_at: datetime
    updated_at: datetime | None
    semantic_kind: str
    geometry: MapGeometry
    attribution: str
    status: CopStatus
    uncertainty: str
    confidence: float | None
    authority: MapFeatureAuthority = field(
        init=False, default=MapFeatureAuthority.ANALYTICAL_GENERATED
    )

    def __post_init__(self) -> None:
        if not self.source_asset_ids or not self.visual_observation_ids:
            raise ValueError(
                "Analytical map features require asset and observation provenance."
            )
        if not self.attribution.strip() or not self.uncertainty.strip():
            raise ValueError(
                "Analytical map features require visible attribution and uncertainty."
            )
        if self.confidence is not None and not 0 <= self.confidence <= 1:
            raise ValueError(
                "Analytical feature confidence must be between zero and one."
            )


@dataclass(frozen=True, slots=True)
class SourceMapLayer:
    """Layer whose features all originate from explicit source geometry."""

    layer_id: str
    physical_event_id: str
    title: str
    semantic_kind: str
    features: tuple[SourceMapFeature, ...]
    source_ids: tuple[str, ...]
    source_asset_ids: tuple[str, ...]
    created_at: datetime
    updated_at: datetime
    status: CopStatus
    uncertainty: str
    attribution: str

    def __post_init__(self) -> None:
        if not self.features or any(
            feature.physical_event_id != self.physical_event_id
            for feature in self.features
        ):
            raise ValueError("Source layers require same-event source features.")
        if set(self.source_ids) != {item.source_id for item in self.features}:
            raise ValueError("Source layer source lineage must match its features.")
        if set(self.source_asset_ids) != {
            asset_id for item in self.features for asset_id in item.source_asset_ids
        }:
            raise ValueError("Source layer asset lineage must match its features.")
        if not self.semantic_kind.strip() or not self.uncertainty.strip():
            raise ValueError("Source layers require semantics and uncertainty.")


@dataclass(frozen=True, slots=True)
class AnalyticalMapLayer:
    """Layer whose features are explicitly generated analytical products."""

    layer_id: str
    physical_event_id: str
    title: str
    semantic_kind: str
    features: tuple[AnalyticalMapFeature, ...]
    source_asset_ids: tuple[str, ...]
    visual_observation_ids: tuple[str, ...]
    created_at: datetime
    updated_at: datetime
    status: CopStatus
    uncertainty: str
    attribution: str

    def __post_init__(self) -> None:
        if not self.features or any(
            feature.physical_event_id != self.physical_event_id
            for feature in self.features
        ):
            raise ValueError(
                "Analytical layers require same-event analytical features."
            )
        if set(self.source_asset_ids) != {
            asset_id for item in self.features for asset_id in item.source_asset_ids
        }:
            raise ValueError("Analytical layer asset lineage must match its features.")
        if set(self.visual_observation_ids) != {
            observation_id
            for item in self.features
            for observation_id in item.visual_observation_ids
        }:
            raise ValueError(
                "Analytical layer observation lineage must match its features."
            )
        if not self.semantic_kind.strip() or not self.uncertainty.strip():
            raise ValueError("Analytical layers require semantics and uncertainty.")


CopLayer = SourceMapLayer | AnalyticalMapLayer


@dataclass(frozen=True, slots=True)
class CommonOperationalPicture:
    """Renderer-independent, provenance-bearing map product."""

    cop_id: str
    physical_event_id: str
    multimodal_state_version: str
    created_at: datetime
    updated_at: datetime
    status: CopStatus
    layers: tuple[CopLayer, ...]

    def __post_init__(self) -> None:
        if any(
            layer.physical_event_id != self.physical_event_id for layer in self.layers
        ):
            raise ValueError("Every COP layer must describe the same physical event.")
