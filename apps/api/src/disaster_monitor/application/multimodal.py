"""Application-layer inputs and model-neutral visual-analysis results."""

from dataclasses import dataclass
from datetime import datetime

from disaster_monitor.domain.disaster import Disaster
from disaster_monitor.domain.multimodal import (
    CaptureRole,
    DamageLevel,
    MultimodalAsset,
    VisualAnalysisConfiguration,
)


@dataclass(frozen=True, slots=True)
class AssetAdmissionInput:
    """Bounded bytes and explicit metadata supplied at the application boundary."""

    content: bytes
    attribution: str
    captured_at: datetime | None = None
    footprint_coordinates: tuple[tuple[tuple[float, float], ...], ...] | None = None
    footprint_crs: str = "EPSG:4326"
    declared_disaster: Disaster | None = None
    declared_country_code: str | None = None
    capture_role: CaptureRole = CaptureRole.UNKNOWN
    canonical_url: str | None = None
    dataset_id: str | None = None
    license_name: str | None = None
    processing_level: str | None = None
    parent_asset_ids: tuple[str, ...] = ()
    event_id_hint: str | None = None


@dataclass(frozen=True, slots=True)
class VisualAnalysisRequest:
    """One bounded damage-and-VQA request over an already admitted asset."""

    asset: MultimodalAsset
    question: str | None


@dataclass(frozen=True, slots=True)
class VisualModelPrediction:
    """Strict canonical output from a replaceable visual model adapter."""

    damage_level: DamageLevel
    damage_confidence: float | None
    damage_cues: tuple[str, ...]
    answer: str | None
    answerable: bool
    answer_confidence: float | None
    answer_cues: tuple[str, ...]
    configuration: VisualAnalysisConfiguration


@dataclass(frozen=True, slots=True)
class VisualModelReadiness:
    """Reproducibility metadata for the configured local visual model."""

    runtime_available: bool
    model_available: bool
    model_id: str
    model_digest: str | None
    adapter_version: str
    prompt_version: str
    preprocessing_version: str
