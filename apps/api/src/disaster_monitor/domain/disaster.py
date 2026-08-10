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
    polygons: tuple[tuple[tuple[float, float], ...], ...] = ()

    def contains(self, latitude: float, longitude: float) -> bool:
        """Return whether a coordinate lies in the represented area."""
        in_bounds = (
            self.min_latitude <= latitude <= self.max_latitude
            and self.min_longitude <= longitude <= self.max_longitude
        )
        if not in_bounds or not self.polygons:
            return in_bounds
        return any(
            _point_in_polygon(latitude, longitude, polygon) for polygon in self.polygons
        )


def _point_in_polygon(
    latitude: float,
    longitude: float,
    polygon: tuple[tuple[float, float], ...],
) -> bool:
    """Return point membership using a deterministic ray-casting boundary test."""
    inside = False
    previous = polygon[-1]
    for current in polygon:
        current_latitude, current_longitude = current
        previous_latitude, previous_longitude = previous
        intersects = (current_latitude > latitude) != (previous_latitude > latitude)
        if intersects:
            boundary_longitude = (previous_longitude - current_longitude) * (
                latitude - current_latitude
            ) / (previous_latitude - current_latitude) + current_longitude
            if longitude <= boundary_longitude:
                inside = not inside
        previous = current
    return inside


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

    def __post_init__(self) -> None:
        if not self.source_id.strip():
            raise ValueError("A source reference requires a stable source ID.")
        if not self.canonical_url.startswith("https://"):
            raise ValueError("A source reference requires a canonical HTTPS URL.")

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
        normalized = value.strip().lower()
        identifiers = {
            item.strip().lower()
            for item in (self.event_id, *self.provider_ids)
            if item.strip()
        }
        if ":" in normalized:
            return normalized in identifiers
        return normalized in {
            identifier.partition(":")[2] if ":" in identifier else identifier
            for identifier in identifiers
        }

    @property
    def jma_event_id(self) -> str | None:
        """Return the preserved JMA identifier, if one was clustered here."""
        for value in (self.event_id, *self.provider_ids):
            if value.lower().startswith("jma:"):
                return value.removeprefix("jma:")
        return None


@dataclass(frozen=True, slots=True)
class EventObservationAssignment:
    """Auditable assignment of one provider observation to a physical event."""

    observation_key: str
    physical_event_id: str
    status: EventAssignmentStatus
    rationale: str
    compatible_observation_keys: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class PhysicalEventIdentity:
    """One conservatively resolved physical event and all source observations."""

    physical_event_id: str
    event: DisasterEvent
    observations: tuple[DisasterEvent, ...]
    assignments: tuple[EventObservationAssignment, ...]


@dataclass(frozen=True, slots=True)
class PhysicalEventIdentityResult:
    """Deterministic partition plus any deliberately unresolved assignments."""

    physical_events: tuple[PhysicalEventIdentity, ...]
    ambiguous_assignments: tuple[EventObservationAssignment, ...] = ()


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


@dataclass(frozen=True, slots=True)
class EvidenceChronology:
    """All relevant times plus the centralized effective comparison time."""

    observed_at: datetime | None
    published_at: datetime | None
    updated_at: datetime | None
    retrieved_at: datetime
    effective_at: datetime


@dataclass(frozen=True, slots=True)
class EvidenceObservation:
    """One immutable fact observation with complete report/source lineage."""

    observation_id: str
    claim_key: str
    fact: ReportedFact
    report: SituationReport
    chronology: EvidenceChronology


@dataclass(frozen=True, slots=True)
class EvidenceObservationState:
    """Classification of one retained observation in a claim history."""

    observation: EvidenceObservation
    disposition: EvidenceDisposition
    freshness: EvidenceFreshness
    rule_id: str


@dataclass(frozen=True, slots=True)
class ClaimEvidenceState:
    """Current selection and complete retained history for one claim."""

    claim_key: str
    availability: EvidenceAvailability
    current: EvidenceObservation | None
    history: tuple[EvidenceObservationState, ...]
    omission_reports: tuple[SourceReference, ...] = ()


@dataclass(frozen=True, slots=True)
class EvidenceWorldState:
    """Request-scoped canonical evidence state for one physical event."""

    state_version: str
    physical_event: PhysicalEventIdentity
    claims: tuple[ClaimEvidenceState, ...]
    reports: tuple[SituationReport, ...]
    evaluated_at: datetime

    def claim(self, claim_key: str) -> ClaimEvidenceState:
        """Return a typed absent state when no usable claim history exists."""
        for claim in self.claims:
            if claim.claim_key == claim_key:
                return claim
        return ClaimEvidenceState(
            claim_key=claim_key,
            availability=EvidenceAvailability.ABSENT,
            current=None,
            history=(),
            omission_reports=(),
        )


@dataclass(frozen=True, slots=True)
class HypothesisFeature:
    """Public rule contribution; this is audit metadata, not chain-of-thought."""

    rule_id: str
    description: str
    contribution: float


@dataclass(frozen=True, slots=True)
class HypothesisArtifact:
    """A deterministic inferred product kept structurally apart from observations."""

    hypothesis_id: str
    proposition: str
    probability: float
    supporting_evidence_ids: tuple[str, ...]
    contradicting_evidence_ids: tuple[str, ...]
    evaluated_at: datetime
    state_version: str
    rationale_features: tuple[HypothesisFeature, ...]
    truth_status: HypothesisTruthStatus = HypothesisTruthStatus.INFERRED

    def __post_init__(self) -> None:
        if not 0.0 <= self.probability <= 1.0:
            raise ValueError("Hypothesis probability must be between zero and one.")
