"""Typed, versioned USGS earthquake product context."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from math import isfinite

from disaster_monitor.domain.disaster_types import _is_aware


class ShakeMeasure(StrEnum):
    MMI = "mmi"
    PGA = "pga"
    PGV = "pgv"


class GroundFailureKind(StrEnum):
    LANDSLIDE = "landslide"
    LIQUEFACTION = "liquefaction"


@dataclass(frozen=True, slots=True)
class ProductReference:
    product_id: str
    product_type: str
    version: str
    status: str
    updated_at: datetime
    event_id: str

    def __post_init__(self) -> None:
        if any(
            not value.strip()
            for value in (
                self.product_id,
                self.product_type,
                self.version,
                self.status,
                self.event_id,
            )
        ):
            raise ValueError("Earthquake products require identity and version.")
        if not _is_aware(self.updated_at):
            raise ValueError("Earthquake product times must be timezone-aware.")


@dataclass(frozen=True, slots=True)
class ProductBounds:
    min_latitude: float
    min_longitude: float
    max_latitude: float
    max_longitude: float

    def __post_init__(self) -> None:
        values = (
            self.min_latitude,
            self.min_longitude,
            self.max_latitude,
            self.max_longitude,
        )
        if not all(isfinite(value) for value in values):
            raise ValueError("Product bounds must be finite.")
        if not (
            -90 <= self.min_latitude < self.max_latitude <= 90
            and -180 <= self.min_longitude < self.max_longitude <= 180
        ):
            raise ValueError("Product bounds are invalid.")


@dataclass(frozen=True, slots=True)
class ShakeMapLayer:
    product: ProductReference
    measure: ShakeMeasure
    unit: str
    coverage_url: str
    coverage_sha256: str | None
    bounds: ProductBounds
    maximum: float | None
    overlay_url: str | None = None
    legend_url: str | None = None


@dataclass(frozen=True, slots=True)
class IntensityExposure:
    intensity: float
    population: int
    economic_exposure_usd: float | None = None


@dataclass(frozen=True, slots=True)
class ProbabilityBin:
    minimum: float
    maximum: float
    probability: float
    unit: str

    def __post_init__(self) -> None:
        if self.minimum < 0 or self.maximum < self.minimum:
            raise ValueError("Probability-bin limits are invalid.")
        if not 0 <= self.probability <= 1:
            raise ValueError("Probability must be between zero and one.")


@dataclass(frozen=True, slots=True)
class PagerImpact:
    product: ProductReference
    alert_level: str
    exposure_by_intensity: tuple[IntensityExposure, ...]
    fatality_probability_bins: tuple[ProbabilityBin, ...]
    economic_loss_probability_bins: tuple[ProbabilityBin, ...]
    interpretation: str


@dataclass(frozen=True, slots=True)
class GroundFailureLayer:
    product: ProductReference
    shakemap_version: str
    kind: GroundFailureKind
    alert_level: str
    hazard_value: float
    population_exposed: int
    bounds: ProductBounds
    raster_url: str
    raster_sha256: str | None
    interpretation: str


@dataclass(frozen=True, slots=True)
class AftershockProbability:
    magnitude: float
    probability: float
    lower_count_95: float
    upper_count_95: float


@dataclass(frozen=True, slots=True)
class AftershockWindow:
    label: str
    starts_at: datetime
    ends_at: datetime
    probabilities: tuple[AftershockProbability, ...]


@dataclass(frozen=True, slots=True)
class AftershockForecast:
    product: ProductReference
    model_name: str
    created_at: datetime
    expires_at: datetime
    advisory_time_frame: str
    latitude: float
    longitude: float
    radius_km: float
    windows: tuple[AftershockWindow, ...]
    global_scope: bool
    interpretation: str


@dataclass(frozen=True, slots=True)
class EarthquakeContext:
    event_id: str
    shakemap_layers: tuple[ShakeMapLayer, ...]
    pager: PagerImpact | None
    ground_failure: tuple[GroundFailureLayer, ...]
    aftershock_forecast: AftershockForecast | None
    retrieved_at: datetime
