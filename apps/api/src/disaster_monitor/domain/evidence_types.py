"""Foundational evidence classifications and source provenance."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


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


class EventAssignmentStatus(StrEnum):
    """Whether an observation has a unique physical-event assignment."""

    ASSIGNED = "assigned"
    AMBIGUOUS = "ambiguous"


class EvidenceAvailability(StrEnum):
    """Whether a claim has a usable current observation."""

    PRESENT = "present"
    ABSENT = "absent"


class EvidenceDisposition(StrEnum):
    """Temporal role of an observation in a canonical claim history."""

    CURRENT = "current"
    SUPERSEDED = "superseded"
    CONFLICTING = "conflicting"
    DUPLICATE = "duplicate"
    UNUSABLE = "unusable"


class EvidenceFreshness(StrEnum):
    """Freshness of one observation at world-state evaluation time."""

    FRESH = "fresh"
    STALE = "stale"


class HypothesisTruthStatus(StrEnum):
    """Epistemic type for products that are never observations."""

    INFERRED = "inferred"


@dataclass(frozen=True, slots=True)
class SourceReference:
    """A canonical source and the distinct timestamps attached to it."""

    source_id: str
    publisher: str
    title: str
    canonical_url: str
    published_at: datetime | None
    updated_at: datetime | None
    retrieved_at: datetime
    authority: SourceAuthority = SourceAuthority.SECONDARY
    snapshot_id: str | None = None

    def __post_init__(self) -> None:
        if not self.source_id.strip():
            raise ValueError("A source reference requires a stable source ID.")
        if not self.canonical_url.startswith("https://"):
            raise ValueError("A source reference requires a canonical HTTPS URL.")
        if self.snapshot_id is not None and not self.snapshot_id.strip():
            raise ValueError("A source snapshot ID must not be empty.")

    @property
    def effective_at(self) -> datetime:
        """Return the best timestamp for freshness and conflict handling."""
        return self.updated_at or self.published_at or self.retrieved_at
