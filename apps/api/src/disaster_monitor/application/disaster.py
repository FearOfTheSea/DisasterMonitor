"""Provider-neutral types for source-backed disaster reports.

These types intentionally contain facts and provenance, rather than provider
payloads.  Provider adapters translate their responses into this vocabulary
before an application service can use them.
"""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class RequestType(StrEnum):
    """Deterministic high-level request classifications."""

    CURRENT_DISASTER = "current_disaster"
    GENERAL_DISASTER = "general_disaster"
    MAP_LOCATION = "map_location"
    AMBIGUOUS = "ambiguous"


class FactStatus(StrEnum):
    """How confidently a source presents a reported value."""

    CONFIRMED = "confirmed"
    PRELIMINARY = "preliminary"
    ESTIMATED = "estimated"
    DISPUTED = "disputed"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class DisasterQuery:
    """Normalized user intent for a bounded current-disaster lookup."""

    hazard: str
    geography: str
    country_code: str
    time_intent: str
    focus: tuple[str, ...]
    time_window_days: int = 30
    date_from: datetime | None = None
    date_to: datetime | None = None
    magnitude: float | None = None
    prefecture: str | None = None
    city: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    event_identifier: str | None = None


@dataclass(frozen=True, slots=True)
class SourceReference:
    """A canonical source and the distinct timestamps attached to it."""

    publisher: str
    title: str
    canonical_url: str
    published_at: datetime | None
    updated_at: datetime | None
    retrieved_at: datetime

    @property
    def effective_at(self) -> datetime:
        """Return the best timestamp for freshness and conflict handling."""
        return self.updated_at or self.published_at or self.retrieved_at


@dataclass(frozen=True, slots=True)
class DisasterEvent:
    """A normalized candidate earthquake event."""

    event_id: str
    hazard: str
    location: str
    country: str
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


@dataclass(frozen=True, slots=True)
class ProviderIssue:
    """A user-safe description of a provider problem."""

    provider: str
    message: str


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


@dataclass(frozen=True, slots=True)
class ReportSection:
    """A section suitable for both text and structured UI rendering."""

    title: str
    content: str


@dataclass(frozen=True, slots=True)
class SelectedEventSummary:
    """Stable event metadata exposed at the API boundary."""

    event_id: str
    hazard: str
    location: str
    event_time: datetime
    magnitude: float | None
    intensity: str | None
    depth_km: float | None
    source: SourceReference


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
