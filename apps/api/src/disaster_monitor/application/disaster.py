"""Application workflow types for source-backed disaster reporting."""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from disaster_monitor.domain.disaster import (
    Country,
    Disaster,
    DisasterEvent,
    EventGeographyStatus,
    EventGeometry,
    EventMeasurement,
    EvidenceWorldState,
    ReportedFact,
    SourceReference,
)


class RequestType(StrEnum):
    """Deterministic high-level request classifications."""

    CURRENT_DISASTER = "current_disaster"
    GENERAL_DISASTER = "general_disaster"
    MAP_LOCATION = "map_location"
    AMBIGUOUS = "ambiguous"


class QueryParseStatus(StrEnum):
    """Deterministic outcomes from disaster intent parsing."""

    MATCHED = "matched"
    NO_DISASTER = "no_disaster"
    NO_COUNTRY = "no_country"
    MULTIPLE_DISASTERS = "multiple_disasters"
    MULTIPLE_COUNTRIES = "multiple_countries"
    DATE_TIMEZONE_UNAVAILABLE = "date_timezone_unavailable"


class GeographicScope(StrEnum):
    """Explicit geographic authority requested by a normalized task."""

    COUNTRY = "country"
    WORLDWIDE = "worldwide"


class WorldwideSelectionIntent(StrEnum):
    """Neutral ranking intent interpreted by the disaster policy."""

    LATEST = "latest"
    STRONGEST = "strongest"


@dataclass(frozen=True, slots=True)
class EventDiscriminator:
    """Neutral key/value discriminator interpreted by disaster-owned policies."""

    kind: str
    value: str


@dataclass(frozen=True, slots=True)
class WorldwideDisasterQuery:
    """Bounded worldwide lookup with no invented country identity."""

    disaster: Disaster
    selection_intent: WorldwideSelectionIntent = WorldwideSelectionIntent.LATEST
    time_window_days: int = 30
    limit: int = 50


@dataclass(frozen=True, slots=True)
class DisasterQuery:
    """Normalized user intent for a bounded current-disaster lookup."""

    disaster: Disaster
    country: Country
    time_intent: str
    focus: tuple[str, ...]
    time_window_days: int = 30
    date_from: datetime | None = None
    date_to: datetime | None = None
    prefecture: str | None = None
    city: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    event_discriminators: tuple[EventDiscriminator, ...] = ()

    def discriminator(self, kind: str) -> str | None:
        for item in self.event_discriminators:
            if item.kind == kind:
                return item.value
        return None

    @property
    def geography(self) -> str:
        """Return the canonical country name for display-only compatibility."""
        return self.country.canonical_name

    @property
    def country_code(self) -> str:
        """Return the canonical ISO alpha-3 code."""
        return self.country.alpha3_code


@dataclass(frozen=True, slots=True)
class WorldwideDisasterEvent:
    """Source-backed event discovered without assigning it to a country."""

    event_id: str
    disaster: Disaster
    location: str
    event_time: datetime
    source: SourceReference
    geometry: EventGeometry | None = None
    measurements: tuple[EventMeasurement, ...] = ()
    provider_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class DisasterQueryParseResult:
    """A parsed query or an explicit deterministic limitation."""

    status: QueryParseStatus
    query: DisasterQuery | None = None
    detail: str | None = None


@dataclass(frozen=True, slots=True)
class RequestClassification:
    """Deterministic request type and optional normalized query."""

    request_type: RequestType
    query: DisasterQuery | None
    parse_status: QueryParseStatus | None = None
    detail: str | None = None


@dataclass(frozen=True, slots=True)
class ProviderIssue:
    """A user-safe, structured description of a provider problem."""

    provider: str
    message: str
    reason_code: str = "invalid_payload"
    retryable: bool = False
    http_status: int | None = None
    detail: str | None = None


@dataclass(frozen=True, slots=True)
class ProviderBatch[T]:
    """Provider records plus non-fatal failures from a composite source."""

    records: tuple[T, ...] = ()
    issues: tuple[ProviderIssue, ...] = ()


@dataclass(frozen=True, slots=True)
class EvidencePacket:
    """Small, normalized evidence packet used by report generation."""

    query: DisasterQuery
    event: DisasterEvent
    facts: tuple[ReportedFact, ...]
    narratives: tuple[str, ...]
    sources: tuple[SourceReference, ...]
    conflicts: tuple[str, ...]
    warnings: tuple[str, ...]
    retrieved_at: datetime
    stale: bool
    completeness: str = "partial"
    partial: bool = True
    world_state: EvidenceWorldState | None = None


@dataclass(frozen=True, slots=True)
class ReportSection:
    """A section suitable for both text and structured UI rendering."""

    title: str
    content: str


@dataclass(frozen=True, slots=True)
class SelectedEventSummary:
    """Stable event metadata exposed at the API boundary."""

    event_id: str
    disaster: Disaster
    location: str
    event_time: datetime
    geometry: EventGeometry | None
    measurements: tuple[EventMeasurement, ...]
    source: SourceReference
    geography_status: EventGeographyStatus
    provider_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class DisasterReport:
    """Complete current-disaster result, including degraded-operation details."""

    message: str
    response_type: str
    selected_event: SelectedEventSummary | None
    retrieval_time: datetime
    sources: tuple[SourceReference, ...]
    warnings: tuple[str, ...]
    sections: tuple[ReportSection, ...]
    partial: bool = False
    capability_gaps: tuple[str, ...] = ()
    investigation_actions: tuple[str, ...] = ()
    termination_reason: str | None = None
