"""Source-footprint exposure estimates and local infrastructure intersections."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from math import isfinite

from disaster_monitor.domain.disaster_types import _is_aware
from disaster_monitor.domain.imagery.regions import Coordinate, MultiPolygon


class ExposureGeometryRole(StrEnum):
    MAPPED_HAZARD = "mapped_hazard"
    FORECAST_HAZARD = "forecast_hazard"
    MODELLED_HAZARD = "modelled_hazard"


class ExposureDatasetRole(StrEnum):
    PRIMARY = "primary"
    SECONDARY = "secondary"


class InfrastructureCategory(StrEnum):
    HOSPITAL = "hospital"
    CLINIC = "clinic"
    SCHOOL = "school"
    FIRE_STATION = "fire_station"
    POLICE = "police"
    BRIDGE = "bridge"
    MAJOR_ROAD = "major_road"
    POWER = "power"
    WATER = "water"
    SHELTER = "shelter"


@dataclass(frozen=True, slots=True)
class ExposureGeometry:
    geometry: MultiPolygon
    role: ExposureGeometryRole
    source_id: str
    source_version: str
    observed_at: datetime

    def __post_init__(self) -> None:
        if not self.source_id.strip() or not self.source_version.strip():
            raise ValueError("Exposure geometry requires source identity and version.")
        if not _is_aware(self.observed_at):
            raise ValueError("Exposure geometry time must be timezone-aware.")


@dataclass(frozen=True, slots=True)
class ExposureDataset:
    dataset_id: str
    publisher: str
    version: str
    vintage: int
    resolution_m: float
    license_name: str
    source_url: str
    role: ExposureDatasetRole
    uncertainty: str

    def __post_init__(self) -> None:
        text_values = (
            self.dataset_id,
            self.publisher,
            self.version,
            self.license_name,
            self.uncertainty,
        )
        if any(not value.strip() for value in text_values):
            raise ValueError("Exposure datasets require complete provenance.")
        if not self.source_url.startswith("https://"):
            raise ValueError("Exposure dataset source URLs must use HTTPS.")
        if not 1900 <= self.vintage <= 2200:
            raise ValueError("Exposure dataset vintage is outside its bounds.")
        if not isfinite(self.resolution_m) or self.resolution_m <= 0:
            raise ValueError("Exposure dataset resolution must be positive.")


@dataclass(frozen=True, slots=True)
class PopulationExposureEstimate:
    estimate_id: str
    population: float
    dataset: ExposureDataset
    geometry_hash: str
    calculated_at: datetime
    lineage: tuple[str, ...]
    lower_bound: float | None = None
    upper_bound: float | None = None

    def __post_init__(self) -> None:
        if (
            not self.estimate_id.strip()
            or not self.geometry_hash.strip()
            or not self.lineage
        ):
            raise ValueError("Population estimates require identity and lineage.")
        if not isfinite(self.population) or self.population < 0:
            raise ValueError("Population estimates must be finite and non-negative.")
        if not _is_aware(self.calculated_at):
            raise ValueError("Population estimate time must be timezone-aware.")
        if self.lower_bound is not None and self.lower_bound < 0:
            raise ValueError("Population lower bounds cannot be negative.")
        if self.upper_bound is not None and self.upper_bound < self.population:
            raise ValueError("Population upper bounds cannot be below the estimate.")


@dataclass(frozen=True, slots=True)
class InfrastructureAsset:
    asset_id: str
    name: str
    category: InfrastructureCategory
    source_dataset_id: str
    source_version: str
    coordinate: Coordinate | None = None
    geometry: MultiPolygon | None = None
    path: tuple[Coordinate, ...] = ()

    def __post_init__(self) -> None:
        if any(
            not value.strip()
            for value in (
                self.asset_id,
                self.name,
                self.source_dataset_id,
                self.source_version,
            )
        ):
            raise ValueError("Infrastructure assets require identity and provenance.")
        representations = sum(
            (self.coordinate is not None, self.geometry is not None, bool(self.path))
        )
        if representations != 1:
            raise ValueError("An infrastructure asset requires exactly one geometry.")
        if self.path and len(self.path) < 2:
            raise ValueError("Infrastructure paths require at least two coordinates.")


@dataclass(frozen=True, slots=True)
class PopulationDisagreement:
    primary_dataset_id: str
    comparison_dataset_id: str
    absolute_difference: float
    relative_difference: float | None


@dataclass(frozen=True, slots=True)
class ExposureAnalysis:
    geometry: ExposureGeometry
    population_estimates: tuple[PopulationExposureEstimate, ...]
    assets: tuple[InfrastructureAsset, ...]
    population_disagreement: PopulationDisagreement | None
    display_label: str
    calculated_at: datetime
    limitations: tuple[str, ...]
