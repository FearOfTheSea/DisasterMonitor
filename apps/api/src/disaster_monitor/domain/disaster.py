"""Stable source-backed disaster concepts."""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class Hazard(StrEnum):
    """Disaster hazards recognized by deterministic request parsing."""

    EARTHQUAKE = "earthquake"
    TSUNAMI = "tsunami"
    FLOOD = "flood"
    WILDFIRE = "wildfire"
    LANDSLIDE = "landslide"
    TROPICAL_CYCLONE = "tropical_cyclone"


class BoundaryValidationQuality(StrEnum):
    """Strength of a geographic membership decision."""

    BOUNDING_BOX = "bounding_box"
    POLYGON = "polygon"


@dataclass(frozen=True, slots=True)
class GeographicArea:
    """A bounded query area and its validation quality."""

    min_latitude: float
    max_latitude: float
    min_longitude: float
    max_longitude: float
    validation_quality: BoundaryValidationQuality = (
        BoundaryValidationQuality.BOUNDING_BOX
    )

    def contains(self, latitude: float, longitude: float) -> bool:
        """Return whether a coordinate lies in the represented area."""
        return (
            self.min_latitude <= latitude <= self.max_latitude
            and self.min_longitude <= longitude <= self.max_longitude
        )


@dataclass(frozen=True, slots=True)
class Country:
    """Canonical country metadata used by queries and provider records."""

    alpha3_code: str
    canonical_name: str
    aliases: tuple[str, ...]
    geographic_area: GeographicArea
    default_timezone: str | None = None


class FactStatus(StrEnum):
    """How confidently a source presents a reported value."""

    CONFIRMED = "confirmed"
    PRELIMINARY = "preliminary"
    ESTIMATED = "estimated"
    DISPUTED = "disputed"
    UNKNOWN = "unknown"


class CorrelationStatus(StrEnum):
    """How strongly a situation record is tied to the selected event."""

    MATCHED = "matched"
    POSSIBLE = "possible"
    UNMATCHED = "unmatched"


class SourceAuthority(StrEnum):
    """Typed evidence authority assigned by provider adapters."""

    NATIONAL_AUTHORITY = "national_authority"
    SCIENTIFIC_AUTHORITY = "scientific_authority"
    HUMANITARIAN_AGGREGATOR = "humanitarian_aggregator"
    SECONDARY = "secondary"


@dataclass(frozen=True, slots=True)
class SourceReference:
    """A canonical source and the distinct timestamps attached to it."""

    publisher: str
    title: str
    canonical_url: str
    published_at: datetime | None
    updated_at: datetime | None
    retrieved_at: datetime
    authority: SourceAuthority = SourceAuthority.SECONDARY

    @property
    def effective_at(self) -> datetime:
        """Return the best timestamp for freshness and conflict handling."""
        return self.updated_at or self.published_at or self.retrieved_at


@dataclass(frozen=True, slots=True)
class DisasterEvent:
    """A normalized source-backed disaster event."""

    event_id: str
    hazard: Hazard
    location: str
    country: Country
    event_time: datetime
    source: SourceReference
    latitude: float | None = None
    longitude: float | None = None
    magnitude: float | None = None
    magnitude_type: str | None = None
    intensity: str | None = None
    depth_km: float | None = None
    significance: float | None = None
    is_aftershock: bool = False
    parent_event_id: str | None = None
    sequence_id: str | None = None
    provider_ids: tuple[str, ...] = ()

    def has_provider_id(self, value: str) -> bool:
        """Return whether a provider-specific identifier belongs to this event."""
        normalized = value.lower()
        identifiers = {
            item.lower().removeprefix("jma:").removeprefix("usgs:")
            for item in (self.event_id, *self.provider_ids)
        }
        return normalized.removeprefix("jma:").removeprefix("usgs:") in identifiers

    @property
    def jma_event_id(self) -> str | None:
        """Return the preserved JMA identifier, if one was clustered here."""
        for value in (self.event_id, *self.provider_ids):
            if value.lower().startswith("jma:"):
                return value.removeprefix("jma:")
        return None


@dataclass(frozen=True, slots=True)
class ReportedFact:
    """One source-attributed, normalized claim about an event."""

    category: str
    label: str
    value: str
    status: FactStatus
    source: SourceReference
    event_id: str | None = None
    observed_at: datetime | None = None
    claim_id: str | None = None


@dataclass(frozen=True, slots=True)
class SituationReport:
    """A provider-neutral situation update with bounded narrative text."""

    source: SourceReference
    narrative: str
    facts: tuple[ReportedFact, ...] = ()
    event_id: str | None = None
    correlation: CorrelationStatus | None = None
    reported_event_time: datetime | None = None
    locations: tuple[str, ...] = ()
    countries: tuple[str, ...] = ()
    country_codes: tuple[str, ...] = ()
    hazard: Hazard | None = None
    magnitude: float | None = None
    provider_event_ids: tuple[str, ...] = ()
