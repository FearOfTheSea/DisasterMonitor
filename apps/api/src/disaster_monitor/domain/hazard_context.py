"""Typed forecast, slow-onset, wildfire, and baseline-vulnerability context."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from math import isfinite

from disaster_monitor.domain.disaster_types import _is_aware
from disaster_monitor.domain.imagery.regions import Coordinate, MultiPolygon


class HazardLayerRole(StrEnum):
    MODELLED_FORECAST = "modelled_forecast"
    DROUGHT_INDICATOR = "drought_indicator"
    DETECTION = "detection"
    BURNED_AREA_PERIMETER = "burned_area_perimeter"
    FORECAST_DANGER = "forecast_danger"


class DroughtState(StrEnum):
    WATCH = "watch"
    WARNING = "warning"
    ALERT = "alert"
    RECOVERY = "recovery"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class GlofasForecastPoint:
    station_id: str
    coordinate: Coordinate
    valid_at: datetime
    discharge_m3_s: float
    exceedance_probability: float
    return_period_years: float

    def __post_init__(self) -> None:
        if not self.station_id.strip() or not _is_aware(self.valid_at):
            raise ValueError("GloFAS points require identity and valid time.")
        if not all(
            isfinite(value)
            for value in (
                self.discharge_m3_s,
                self.exceedance_probability,
                self.return_period_years,
            )
        ):
            raise ValueError("GloFAS forecast values must be finite.")
        if not 0 <= self.exceedance_probability <= 1:
            raise ValueError("GloFAS probability must be between zero and one.")
        if self.discharge_m3_s < 0 or self.return_period_years <= 0:
            raise ValueError("GloFAS discharge and return period are invalid.")


@dataclass(frozen=True, slots=True)
class GlofasForecast:
    event_id: str
    source_id: str
    model_version: str
    issue_time: datetime
    retrieved_at: datetime
    role: HazardLayerRole
    points: tuple[GlofasForecastPoint, ...]
    interpretation: str


@dataclass(frozen=True, slots=True)
class DroughtEpisode:
    episode_id: str
    source_id: str
    dataset_version: str
    geometry: MultiPolygon
    indicator_name: str
    indicator_value: float
    indicator_unit: str
    state: DroughtState
    window_start: datetime
    window_end: datetime
    retrieved_at: datetime
    role: HazardLayerRole = HazardLayerRole.DROUGHT_INDICATOR
    slow_onset: bool = True

    def __post_init__(self) -> None:
        if any(
            not value.strip()
            for value in (
                self.episode_id,
                self.source_id,
                self.dataset_version,
                self.indicator_name,
                self.indicator_unit,
            )
        ):
            raise ValueError(
                "Drought indicators require complete identity and lineage."
            )
        if not _is_aware(self.window_start) or not _is_aware(self.window_end):
            raise ValueError("Drought windows must be timezone-aware.")
        if self.window_start >= self.window_end:
            raise ValueError("Drought indicator windows must have positive duration.")
        if not self.slow_onset:
            raise ValueError("Drought episodes must retain slow-onset semantics.")


@dataclass(frozen=True, slots=True)
class WildfireContextLayer:
    layer_id: str
    event_id: str
    source_id: str
    role: HazardLayerRole
    version: str
    observed_at: datetime
    retrieved_at: datetime
    wms_url: str
    geometry: MultiPolygon | None
    valid_until: datetime | None
    establishes_incident: bool = False

    def __post_init__(self) -> None:
        if any(
            not value.strip()
            for value in (
                self.layer_id,
                self.event_id,
                self.source_id,
                self.version,
                self.wms_url,
            )
        ):
            raise ValueError("Wildfire layers require identity and version.")
        if not _is_aware(self.observed_at) or not _is_aware(self.retrieved_at):
            raise ValueError("Wildfire layer times must be timezone-aware.")
        if self.valid_until is not None and not _is_aware(self.valid_until):
            raise ValueError("Wildfire layer validity must be timezone-aware.")
        if self.establishes_incident:
            raise ValueError(
                "Context layers cannot establish a verified wildfire event."
            )


@dataclass(frozen=True, slots=True)
class BaselineVulnerabilityContext:
    place_code: str
    place_name: str
    aggregation_level: str
    dataset_version: str
    vintage: int
    risk_index: float
    vulnerability_index: float
    coping_capacity_index: float
    source_id: str
    context_role: str
    interpretation: str

    def __post_init__(self) -> None:
        if self.context_role != "baseline_vulnerability":
            raise ValueError("INFORM context must remain baseline vulnerability.")
        if not 1900 <= self.vintage <= 2200:
            raise ValueError("INFORM vintage is outside its bounds.")
