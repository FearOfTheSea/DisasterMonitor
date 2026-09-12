"""Acquisition identity, capture timing, quality, and comparison values."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta, tzinfo
from enum import StrEnum
from math import isfinite
from typing import Literal

from disaster_monitor.domain.imagery.regions import MultiPolygon


def _is_aware(value: datetime) -> bool:
    return value.tzinfo is not None and value.utcoffset() is not None


class Sensor(StrEnum):
    """First-release Sentinel sensors."""

    SENTINEL_1 = "sentinel-1"
    SENTINEL_2 = "sentinel-2"


class TemporalRole(StrEnum):
    """Role a selected acquisition plays in an inspection timeline."""

    PRE_EVENT_REFERENCE = "pre_event_reference"
    FIRST_USEFUL_AFTER_ONSET = "first_useful_after_onset"
    LATEST_USEFUL = "latest_useful"
    EARLIER_REFERENCE = "earlier_reference"
    RECOVERY_CHECKPOINT = "recovery_checkpoint"


class ObservationReadiness(StrEnum):
    """Independent provider/catalog lifecycle states."""

    CATALOGUED = "catalogued"
    RENDERABLE = "renderable"
    PROCESSING = "processing"
    DOWNLOADED = "downloaded"
    UNAVAILABLE = "unavailable"


class QualityState(StrEnum):
    """Regional quality outcome for one acquisition."""

    USEFUL = "useful"
    PARTIAL = "partial"
    OBSCURED = "obscured"
    UNCERTAIN = "uncertain"
    UNCOVERED = "uncovered"


OnsetPrecision = Literal[
    "exact",
    "interval",
    "date_only_with_timezone",
    "date_only_unknown_timezone",
    "user_override",
]


@dataclass(frozen=True, slots=True)
class ImpactOnset:
    """A conservative interval for local impact onset."""

    earliest: datetime
    latest: datetime
    source_id: str
    precision: OnsetPrecision

    def __post_init__(self) -> None:
        if not _is_aware(self.earliest) or not _is_aware(self.latest):
            raise ValueError("Impact onset timestamps must be timezone-aware.")
        if self.latest < self.earliest:
            raise ValueError("Impact onset bounds cannot be reversed.")
        if not self.source_id.strip():
            raise ValueError("Impact onset requires source provenance.")

    @classmethod
    def exact(cls, value: datetime, *, source_id: str) -> ImpactOnset:
        return cls(value, value, source_id, "exact")

    @classmethod
    def interval(
        cls, earliest: datetime, latest: datetime, *, source_id: str
    ) -> ImpactOnset:
        return cls(earliest, latest, source_id, "interval")

    @classmethod
    def from_date(
        cls,
        value: date,
        *,
        source_id: str,
        timezone: tzinfo | None = None,
        user_override: bool = False,
    ) -> ImpactOnset:
        """Expand a date-only claim without inventing UTC midnight."""
        if timezone is not None:
            start = datetime.combine(
                value, datetime.min.time(), tzinfo=timezone
            ).astimezone(UTC)
            end = start + timedelta(days=1)
            precision: OnsetPrecision = (
                "user_override" if user_override else "date_only_with_timezone"
            )
            return cls(start, end, source_id, precision)
        start = datetime.combine(value, datetime.min.time(), tzinfo=UTC) - timedelta(
            hours=14
        )
        end = datetime.combine(
            value + timedelta(days=1), datetime.min.time(), tzinfo=UTC
        ) + timedelta(hours=12)
        precision = "user_override" if user_override else "date_only_unknown_timezone"
        return cls(start, end, source_id, precision)


@dataclass(frozen=True, slots=True)
class CaptureInterval:
    """Actual sensing interval, independent of delivery/provenance timestamps."""

    start: datetime
    end: datetime

    def __post_init__(self) -> None:
        if not _is_aware(self.start) or not _is_aware(self.end):
            raise ValueError("Capture timestamps must be timezone-aware.")
        if self.end < self.start:
            raise ValueError("A capture interval cannot end before it starts.")


@dataclass(frozen=True, slots=True)
class AcquisitionIdentity:
    """Provider-backed identity retained through rendering and export."""

    product_id: str
    provider: str
    revision: str | None = None
    acquisition_id: str | None = None
    datatake_id: str | None = None
    platform: str | None = None
    processing_version: str | None = None
    source_url: str | None = None

    def __post_init__(self) -> None:
        if not self.product_id.strip() or not self.provider.strip():
            raise ValueError("An acquisition requires product and provider identity.")
        for value in (
            self.revision,
            self.acquisition_id,
            self.datatake_id,
            self.platform,
            self.processing_version,
            self.source_url,
        ):
            if value is not None and not value.strip():
                raise ValueError("Acquisition identity fields must not be empty.")

    @property
    def stable_key(self) -> str:
        return ":".join(
            (
                self.provider,
                self.acquisition_id or self.product_id,
                self.revision or "base",
            )
        )


@dataclass(frozen=True, slots=True)
class ObservationQuality:
    """Coverage fractions calculated against the complete requested core."""

    covered_fraction: float
    usable_fraction: float
    obscured_fraction: float
    uncertain_fraction: float
    uncovered_fraction: float
    component_usable_fractions: tuple[tuple[str, float], ...] = ()
    quality_state: QualityState = QualityState.UNCERTAIN
    mask_definition: str = ""

    def __post_init__(self) -> None:
        fractions = (
            self.covered_fraction,
            self.usable_fraction,
            self.obscured_fraction,
            self.uncertain_fraction,
            self.uncovered_fraction,
            *(value for _, value in self.component_usable_fractions),
        )
        if any(not isfinite(value) or not 0 <= value <= 1 for value in fractions):
            raise ValueError(
                "Observation quality fractions must be finite percentages."
            )
        if self.covered_fraction + self.uncovered_fraction > 1.000001:
            raise ValueError("Covered and uncovered fractions cannot exceed the core.")
        if self.usable_fraction > self.covered_fraction + 0.000001:
            raise ValueError("Usable coverage cannot exceed source coverage.")
        if any(
            not component.strip() for component, _ in self.component_usable_fractions
        ):
            raise ValueError("Component coverage requires stable component IDs.")
        if not self.mask_definition.strip():
            raise ValueError(
                "Observation quality requires a versioned mask definition."
            )

    @property
    def minimum_component_usable_fraction(self) -> float:
        if not self.component_usable_fractions:
            return self.usable_fraction
        return min(value for _, value in self.component_usable_fractions)


@dataclass(frozen=True, slots=True)
class Observation:
    """One catalog acquisition with independent readiness and quality states."""

    observation_id: str
    sensor: Sensor
    identity: AcquisitionIdentity
    capture: CaptureInterval
    footprint: MultiPolygon
    readiness: ObservationReadiness
    quality: ObservationQuality | None = None
    acquisition_group_id: str | None = None
    mode: str | None = None
    relative_orbit: int | None = None
    orbit_direction: str | None = None
    polarizations: tuple[str, ...] = ()
    cloud_cover_fraction: float | None = None
    recipe_version: str | None = None
    provider_published_at: datetime | None = None
    catalog_updated_at: datetime | None = None
    retrieved_at: datetime | None = None
    assets: tuple[tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        if not self.observation_id.strip():
            raise ValueError("An observation requires stable identity.")
        if (
            self.identity.source_url is not None
            and not self.identity.source_url.startswith(("https://", "http://"))
        ):
            raise ValueError("Observation source URLs must use HTTP(S).")
        for value in (
            self.provider_published_at,
            self.catalog_updated_at,
            self.retrieved_at,
        ):
            if value is not None and not _is_aware(value):
                raise ValueError(
                    "Observation provenance timestamps must be timezone-aware."
                )
        if self.relative_orbit is not None and self.relative_orbit < 1:
            raise ValueError("A relative orbit must be positive.")
        if (
            self.cloud_cover_fraction is not None
            and not 0 <= self.cloud_cover_fraction <= 1
        ):
            raise ValueError("Cloud cover must be a fraction between zero and one.")
        if any(not key.strip() or not value.strip() for key, value in self.assets):
            raise ValueError("Observation asset names and URLs must be non-empty.")

    @property
    def group_key(self) -> str:
        return (
            self.acquisition_group_id
            or self.identity.acquisition_id
            or self.identity.product_id
        )

    @property
    def is_renderable(self) -> bool:
        return self.readiness in {
            ObservationReadiness.RENDERABLE,
            ObservationReadiness.DOWNLOADED,
        }


def radar_comparison_compatibility(
    before: Observation, after: Observation
) -> tuple[bool, str]:
    """Check the explicit S1 comparison dimensions before visual ranking."""
    if before.sensor is not Sensor.SENTINEL_1 or after.sensor is not Sensor.SENTINEL_1:
        return False, "radar_comparison_requires_sentinel_1"
    if before.mode != after.mode:
        return False, "mode_mismatch"
    if before.relative_orbit is None or after.relative_orbit is None:
        return False, "relative_orbit_missing"
    if before.relative_orbit != after.relative_orbit:
        return False, "relative_orbit_mismatch"
    if before.orbit_direction != after.orbit_direction:
        return False, "orbit_direction_mismatch"
    if before.polarizations != after.polarizations:
        return False, "polarization_mismatch"
    if before.recipe_version != after.recipe_version:
        return False, "recipe_mismatch"
    return True, "compatible"
