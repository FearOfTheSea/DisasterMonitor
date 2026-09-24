"""Application workflow types for source-backed disaster reporting."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum

from disaster_monitor.application.evidence.inspection import (
    EvidenceClaimInspection,
    EvidenceTimelineEntry,
)
from disaster_monitor.application.ports.provider_failures import ProviderFailureReason
from disaster_monitor.domain.disaster import (
    Country,
    CycloneMapLayer,
    Disaster,
    DisasterEvent,
    EventGeographyStatus,
    EventGeometry,
    EventMeasurement,
    EventTimePrecision,
    EvidenceWorldState,
    IncidentActivityStatus,
    ReportedFact,
    SourceReference,
)
from disaster_monitor.domain.disaster import ObservationKind as ObservationKind
from disaster_monitor.domain.disaster_types import validate_event_temporality


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
    INVALID_DATE = "invalid_date"
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
    occurrence_start: datetime | None = None
    occurrence_end: datetime | None = None

    def __post_init__(self) -> None:
        if (self.occurrence_start is None) != (self.occurrence_end is None):
            raise ValueError("Worldwide occurrence intervals require both bounds.")
        if self.occurrence_start is not None:
            if self.occurrence_start.tzinfo is None or self.occurrence_end is None:
                raise ValueError("Worldwide occurrence bounds must be timezone-aware.")
            if self.occurrence_end.tzinfo is None:
                raise ValueError("Worldwide occurrence bounds must be timezone-aware.")
            if self.occurrence_start > self.occurrence_end:
                raise ValueError("Worldwide occurrence bounds are out of order.")
            if self.occurrence_end - self.occurrence_start > timedelta(days=366):
                raise ValueError(
                    "Worldwide occurrence intervals may span at most 366 days."
                )


def worldwide_retrieval_time_bounds(
    query: WorldwideDisasterQuery, *, now: datetime
) -> tuple[datetime, datetime]:
    """Return the explicit UTC occurrence interval or the bounded rolling window."""
    if query.occurrence_start is not None and query.occurrence_end is not None:
        return query.occurrence_start, query.occurrence_end
    return now - timedelta(days=query.time_window_days), now


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
    selection_intent: WorldwideSelectionIntent = WorldwideSelectionIntent.LATEST
    location_hint: str | None = None

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


def retrieval_time_bounds(
    query: DisasterQuery,
    *,
    now: datetime,
    end_margin: timedelta = timedelta(),
) -> tuple[datetime, datetime]:
    """Return bounded provider/filter times, widening only named regional dates.

    Country catalogs carry one deterministic default timezone, while a named place
    can sit in another timezone.  A bounded tolerance prevents a valid event from
    disappearing at a country-wide timezone boundary without changing the user's
    explicit date fields or admitting an unbounded search.
    """
    start = query.date_from or now - timedelta(days=query.time_window_days)
    end = (query.date_to or now) + end_margin
    if (
        query.location_hint
        and query.date_from is not None
        and query.date_to is not None
    ):
        tolerance = timedelta(hours=14)
        return start - tolerance, end + tolerance
    return start, end


@dataclass(frozen=True, slots=True)
class WorldwideDisasterEvent:
    """Source-backed event discovered without assigning it to a country."""

    event_id: str
    disaster: Disaster
    location: str
    event_time: datetime
    source: SourceReference
    event_time_end: datetime | None = None
    event_time_precision: EventTimePrecision = EventTimePrecision.EXACT
    geometry: EventGeometry | None = None
    measurements: tuple[EventMeasurement, ...] = ()
    provider_ids: tuple[str, ...] = ()
    lineage_ids: tuple[str, ...] = ()
    observation_kind: ObservationKind = ObservationKind.PHYSICAL_EVENT
    activity_status: IncidentActivityStatus = IncidentActivityStatus.UNKNOWN

    def __post_init__(self) -> None:
        validate_event_temporality(
            self.event_time,
            self.event_time_end,
            self.event_time_precision,
            self.observation_kind,
        )


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
    reason_code: ProviderFailureReason | str = ProviderFailureReason.INVALID_PAYLOAD
    retryable: bool = False
    http_status: int | None = None
    detail: str | None = None


@dataclass(frozen=True, slots=True)
class ProviderBatch[T]:
    """Provider records plus non-fatal failures from a composite source."""

    records: tuple[T, ...] = ()
    issues: tuple[ProviderIssue, ...] = ()
    scan_complete: bool = True
    records_seen: int | None = None


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
    supplemental_geometry: tuple[CycloneMapLayer, ...] = ()
    claims: tuple[EvidenceClaimInspection, ...] = ()
    timeline: tuple[EvidenceTimelineEntry, ...] = ()


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
    lineage_ids: tuple[str, ...] = ()
    supplemental_geometry: tuple[CycloneMapLayer, ...] = ()
    location_source: SourceReference | None = None


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
    claims: tuple[EvidenceClaimInspection, ...] = ()
    timeline: tuple[EvidenceTimelineEntry, ...] = ()
    original_message: str | None = None
    response_language: str | None = None
