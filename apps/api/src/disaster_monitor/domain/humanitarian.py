"""Humanitarian indicators and operational-presence context."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from math import isfinite

from disaster_monitor.domain.disaster_types import _is_aware


class HumanitarianIndicatorKind(StrEnum):
    BASELINE_POPULATION = "baseline_population"
    DISPLACED_PEOPLE = "displaced_people"
    FOOD_INSECURITY = "food_insecurity"


class ContextAvailability(StrEnum):
    AVAILABLE = "available"
    PARTIAL = "partial"
    NO_DATA = "no_data"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True, slots=True)
class HumanitarianIndicator:
    indicator_id: str
    source_id: str
    kind: HumanitarianIndicatorKind
    value: float
    unit: str
    country_code: str
    admin1_code: str | None
    admin1_name: str | None
    reference_period_start: datetime
    reference_period_end: datetime
    dataset_id: str
    dataset_updated_at: datetime
    retrieved_at: datetime
    source_url: str
    license_name: str
    causal_attribution: bool = False
    stale: bool = False
    dimensions: tuple[tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        required = (
            self.indicator_id,
            self.source_id,
            self.unit,
            self.dataset_id,
            self.license_name,
        )
        if any(not value.strip() for value in required):
            raise ValueError("Humanitarian indicators require complete provenance.")
        if len(self.country_code) != 3 or not self.country_code.isalpha():
            raise ValueError("Humanitarian indicators require an ISO alpha-3 code.")
        if not isfinite(self.value) or self.value < 0:
            raise ValueError("Humanitarian indicator values must be non-negative.")
        times = (
            self.reference_period_start,
            self.reference_period_end,
            self.dataset_updated_at,
            self.retrieved_at,
        )
        if any(not _is_aware(value) for value in times):
            raise ValueError("Humanitarian indicator times must be timezone-aware.")
        if self.reference_period_start > self.reference_period_end:
            raise ValueError("Humanitarian reference periods are out of order.")
        if not self.source_url.startswith("https://"):
            raise ValueError("Humanitarian context sources require HTTPS URLs.")
        if (
            self.kind is HumanitarianIndicatorKind.DISPLACED_PEOPLE
            and self.causal_attribution
        ):
            raise ValueError(
                "Generic displacement context cannot assert event causality."
            )
        if any(not key.strip() or not value.strip() for key, value in self.dimensions):
            raise ValueError("Humanitarian indicator dimensions must be complete.")


@dataclass(frozen=True, slots=True)
class OperationalPresence:
    presence_id: str
    source_id: str
    organization: str
    acronym: str | None
    sector: str
    country_code: str
    admin1_code: str | None
    admin1_name: str | None
    dataset_id: str
    dataset_updated_at: datetime
    retrieved_at: datetime
    source_url: str
    license_name: str

    def __post_init__(self) -> None:
        required = (
            self.presence_id,
            self.source_id,
            self.organization,
            self.sector,
            self.dataset_id,
            self.license_name,
        )
        if any(not value.strip() for value in required):
            raise ValueError("Operational presence requires complete provenance.")
        if len(self.country_code) != 3 or not self.country_code.isalpha():
            raise ValueError("Operational presence requires an ISO alpha-3 code.")
        if not _is_aware(self.dataset_updated_at) or not _is_aware(self.retrieved_at):
            raise ValueError("Operational-presence times must be timezone-aware.")
        if not self.source_url.startswith("https://"):
            raise ValueError("Operational-presence sources require HTTPS URLs.")


@dataclass(frozen=True, slots=True)
class HumanitarianContextSnapshot:
    country_code: str
    event_id: str | None
    availability: ContextAvailability
    indicators: tuple[HumanitarianIndicator, ...]
    operational_presence: tuple[OperationalPresence, ...]
    retrieved_at: datetime
    gaps: tuple[str, ...]
    limitations: tuple[str, ...]
