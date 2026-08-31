"""Stable source-backed disaster concepts."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field, replace
from datetime import datetime
from enum import StrEnum
from math import isfinite
from typing import Any, cast


class Disaster(StrEnum):
    """Disasters recognized by deterministic request parsing."""

    EARTHQUAKE = "earthquake"
    FLOOD = "flood"
    WILDFIRE = "wildfire"
    LANDSLIDE = "landslide"
    TROPICAL_CYCLONE = "tropical_cyclone"
    VOLCANIC_ERUPTION = "volcanic_eruption"


class BoundaryValidationQuality(StrEnum):
    """Strength of a geographic membership decision."""

    BOUNDING_BOX = "bounding_box"
    POLYGON = "polygon"


class EventGeographyStatus(StrEnum):
    """How a selected event relates to the requested country's land area."""

    IN_COUNTRY = "in_country"
    COUNTRY_ASSOCIATED_OFFSHORE = "country_associated_offshore"
    WORLDWIDE = "worldwide"


class ProviderTier(StrEnum):
    """Explicit authority tier assigned to a provider observation."""

    PRIMARY = "primary"
    SECONDARY = "secondary"

    @property
    def precedence(self) -> int:
        """Return the deterministic canonical-selection precedence."""
        return 2 if self is ProviderTier.PRIMARY else 1


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

    def distance_to_boundary_km(
        self, latitude: float, longitude: float
    ) -> float | None:
        """Return an approximate distance to the nearest polygon boundary.

        This is intentionally a bounded proximity check, not a replacement for
        polygon membership or a maritime boundary claim.  It is used only to
        identify near-shore events whose provider place text explicitly names
        the requested country.
        """
        if self.contains(latitude, longitude):
            return 0.0
        if not self.polygons:
            return None
        return min(
            _distance_to_segment_km(
                latitude,
                longitude,
                previous[0],
                previous[1],
                current[0],
                current[1],
            )
            for polygon in self.polygons
            for previous, current in zip(
                polygon, polygon[1:] + polygon[:1], strict=True
            )
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


def _distance_to_segment_km(
    latitude: float,
    longitude: float,
    start_latitude: float,
    start_longitude: float,
    end_latitude: float,
    end_longitude: float,
) -> float:
    """Approximate point-to-segment distance in a local equirectangular plane."""
    from math import cos, hypot, radians

    reference_latitude = radians(latitude)

    def project(point_latitude: float, point_longitude: float) -> tuple[float, float]:
        longitude_delta = (point_longitude - longitude + 180) % 360 - 180
        return (
            radians(longitude_delta) * cos(reference_latitude),
            radians(point_latitude - latitude),
        )

    point_x, point_y = 0.0, 0.0
    start_x, start_y = project(start_latitude, start_longitude)
    end_x, end_y = project(end_latitude, end_longitude)
    segment_x = end_x - start_x
    segment_y = end_y - start_y
    segment_length_squared = segment_x * segment_x + segment_y * segment_y
    if segment_length_squared == 0:
        return hypot(start_x, start_y) * 6_371.0088
    projection = max(
        0.0,
        min(
            1.0,
            ((point_x - start_x) * segment_x + (point_y - start_y) * segment_y)
            / segment_length_squared,
        ),
    )
    return (
        hypot(
            point_x - (start_x + projection * segment_x),
            point_y - (start_y + projection * segment_y),
        )
        * 6_371.0088
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


class IncidentPriority(StrEnum):
    """Internal attention class derived from verified evidence state."""

    LOW = "low"
    MODERATE = "moderate"
    HIGH = "high"
    CRITICAL = "critical"


class TriageAutonomyMode(StrEnum):
    """Authority mode for one reversible internal triage decision."""

    AUTONOMOUS_INTERNAL = "autonomous_internal"
    HUMAN_ON_THE_LOOP = "human_on_the_loop"
    HUMAN_IN_THE_LOOP = "human_in_the_loop"


class InternalTriageAction(StrEnum):
    """Closed set of internal-only actions; suppression is deliberately absent."""

    MONITOR_INTERNAL = "monitor_internal"
    QUEUE_INTERNAL = "queue_internal"
    REQUEST_PRIORITY_REVIEW = "request_priority_review"
    ESCALATE_CRITICAL = "escalate_critical"


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


class MeasurementKind(StrEnum):
    """Known source-reported measurements shared by disaster policies."""

    MAGNITUDE = "magnitude"
    INTENSITY = "intensity"
    DEPTH = "depth"
    PROVIDER_SIGNIFICANCE = "provider_significance"
    CONFIDENCE = "confidence"
    FIRE_RADIATIVE_POWER = "fire_radiative_power"
    SEVERITY = "severity"


@dataclass(frozen=True, slots=True)
class EventMeasurement:
    """One typed, source-backed measurement attached to an event."""

    kind: MeasurementKind
    value: float | str
    unit: str | None = None
    source: SourceReference = field(kw_only=True)

    def __post_init__(self) -> None:
        if not isinstance(self.kind, MeasurementKind):
            raise TypeError("An event measurement requires a typed measurement kind.")
        if not isinstance(self.source, SourceReference):
            raise TypeError("An event measurement requires source provenance.")
        if isinstance(self.value, bool) or (
            isinstance(self.value, float) and not isfinite(self.value)
        ):
            raise ValueError("An event measurement value must be finite.")
        if not isinstance(self.value, (int, float, str)):
            raise TypeError("An event measurement value has an unsupported type.")
        if self.unit is not None and not self.unit.strip():
            raise ValueError("An event measurement unit must not be empty.")


class EventGeometryKind(StrEnum):
    """Authoritative geometry shape available for an event."""

    POINT = "point"
    AREA = "area"
    TRACK = "track"
    DESCRIPTIVE = "descriptive"


@dataclass(frozen=True, slots=True)
class EventCoordinate:
    """One WGS84 coordinate preserved exactly as supplied by a source."""

    latitude: float
    longitude: float

    def __post_init__(self) -> None:
        if (
            not isfinite(self.latitude)
            or not isfinite(self.longitude)
            or not -90 <= self.latitude <= 90
            or not -180 <= self.longitude <= 180
        ):
            raise ValueError("An event coordinate is outside the WGS84 extent.")


@dataclass(frozen=True, slots=True)
class EventGeometry:
    """A source-backed point, area, track, or descriptive-only location."""

    kind: EventGeometryKind
    source: SourceReference
    coordinates: tuple[EventCoordinate, ...] = ()
    description: str | None = None
    estimated: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.estimated, bool):
            raise TypeError("Event geometry estimation metadata must be boolean.")
        if self.kind is EventGeometryKind.POINT and len(self.coordinates) != 1:
            raise ValueError("A point event geometry requires one coordinate.")
        if self.kind is EventGeometryKind.AREA and len(self.coordinates) < 3:
            raise ValueError("An area event geometry requires a perimeter.")
        if self.kind is EventGeometryKind.TRACK and len(self.coordinates) < 2:
            raise ValueError("A track event geometry requires two coordinates.")
        if self.kind is EventGeometryKind.DESCRIPTIVE:
            if self.coordinates or not self.description or not self.description.strip():
                raise ValueError(
                    "Descriptive event geometry requires only a description."
                )
        elif self.description is not None and not self.description.strip():
            raise ValueError("An event geometry description must not be empty.")


def point_event_geometry(
    latitude: float,
    longitude: float,
    source: SourceReference,
    *,
    estimated: bool = False,
) -> EventGeometry:
    """Build point geometry without changing or deriving its coordinates."""
    return EventGeometry(
        kind=EventGeometryKind.POINT,
        source=source,
        coordinates=(EventCoordinate(latitude, longitude),),
        estimated=estimated,
    )


def descriptive_event_geometry(
    description: str, source: SourceReference
) -> EventGeometry:
    """Build source-backed descriptive geometry when no authoritative shape exists."""
    return EventGeometry(
        kind=EventGeometryKind.DESCRIPTIVE,
        source=source,
        description=description,
    )


@dataclass(frozen=True, slots=True)
class DisasterEvent:
    """A normalized source-backed disaster event."""

    event_id: str
    disaster: Disaster
    location: str
    country: Country
    event_time: datetime
    source: SourceReference
    geometry: EventGeometry | None = None
    measurements: tuple[EventMeasurement, ...] = ()
    provider_ids: tuple[str, ...] = ()
    geography_status: EventGeographyStatus = EventGeographyStatus.IN_COUNTRY
    provider_tier: ProviderTier = ProviderTier.SECONDARY

    def __post_init__(self) -> None:
        if not isinstance(self.provider_tier, ProviderTier):
            raise TypeError("A disaster event requires a typed provider tier.")
        if not isinstance(self.measurements, tuple) or any(
            not isinstance(item, EventMeasurement) for item in self.measurements
        ):
            raise TypeError("A disaster event requires typed measurements.")

    def measurement(self, kind: MeasurementKind) -> EventMeasurement | None:
        """Return the first retained measurement of a typed kind."""
        for measurement in self.measurements:
            if measurement.kind is kind:
                return measurement
        return None

    def measurements_of(self, kind: MeasurementKind) -> tuple[EventMeasurement, ...]:
        """Return all retained observations of a typed measurement kind."""
        return tuple(item for item in self.measurements if item.kind is kind)

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


@dataclass(frozen=True, slots=True)
class EarthquakeEvent(DisasterEvent):
    """Earthquake-only sequence details kept out of shared event fields."""

    is_aftershock: bool = False
    parent_event_id: str | None = None
    sequence_id: str | None = None

    def __post_init__(self) -> None:
        if self.disaster is not Disaster.EARTHQUAKE:
            raise ValueError("EarthquakeEvent requires the earthquake disaster.")


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

    def __post_init__(self) -> None:
        if not self.observations:
            raise ValueError("A physical event requires at least one observation.")
        if self.event.source not in {item.source for item in self.observations}:
            raise ValueError("A physical event must retain an observed event source.")
        if self.event.geometry is not None and not any(
            item.geometry == self.event.geometry for item in self.observations
        ):
            raise ValueError(
                "A physical event geometry must retain an observed geometry source."
            )
        for measurement in self.event.measurements:
            if not any(measurement in item.measurements for item in self.observations):
                raise ValueError(
                    "A physical event measurement must retain its observation source."
                )


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
    disaster: Disaster | None = None
    measurements: tuple[EventMeasurement, ...] = ()
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
    uncertain_evidence_ids: tuple[str, ...] = ()
    truth_status: HypothesisTruthStatus = HypothesisTruthStatus.INFERRED

    def __post_init__(self) -> None:
        if not 0.0 <= self.probability <= 1.0:
            raise ValueError("Hypothesis probability must be between zero and one.")


@dataclass(frozen=True, slots=True)
class IncidentPrioritySignal:
    """Public policy contribution with direct evidence lineage where applicable."""

    rule_id: str
    detail: str
    score_delta: int
    evidence_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.rule_id.strip() or not self.detail.strip():
            raise ValueError("Priority signals require a rule ID and public detail.")
        if self.score_delta < 0:
            raise ValueError("Uncertainty and evidence cannot reduce priority score.")


@dataclass(frozen=True, slots=True)
class IncidentPriorityAssessment:
    """Deterministic internal ranking result tied to one canonical EW version."""

    assessment_id: str
    physical_event_id: str
    evidence_state_version: str
    priority: IncidentPriority
    score: int
    requires_human_review: bool
    uncertainty_escalated: bool
    signals: tuple[IncidentPrioritySignal, ...]
    assessed_at: datetime

    def __post_init__(self) -> None:
        if not self.assessment_id or not self.physical_event_id:
            raise ValueError("Priority assessments require stable event lineage.")
        if not self.evidence_state_version:
            raise ValueError("Priority assessments require an EW state version.")
        if not 0 <= self.score <= 100:
            raise ValueError("Priority score must be between zero and one hundred.")

    @property
    def is_critical(self) -> bool:
        return self.priority == IncidentPriority.CRITICAL


@dataclass(frozen=True, slots=True)
class InternalTriageDecision:
    """Bounded triage action that cannot create an external operational effect."""

    decision_id: str
    assessment_id: str
    physical_event_id: str
    evidence_state_version: str
    priority: IncidentPriority
    action: InternalTriageAction
    autonomy_mode: TriageAutonomyMode
    reversible: bool
    requires_human_intervention: bool
    policy_rule_ids: tuple[str, ...]
    decided_at: datetime

    def __post_init__(self) -> None:
        if not self.decision_id or not self.assessment_id:
            raise ValueError("Triage decisions require assessment lineage.")
        if not self.physical_event_id or not self.evidence_state_version:
            raise ValueError("Triage decisions require event and EW lineage.")
        if not self.policy_rule_ids:
            raise ValueError("Triage decisions require machine-testable policy rules.")
        if self.autonomy_mode == TriageAutonomyMode.AUTONOMOUS_INTERNAL:
            if self.priority not in {IncidentPriority.LOW, IncidentPriority.MODERATE}:
                raise ValueError(
                    "Autonomous triage is limited to low/moderate priority."
                )
            if self.action not in {
                InternalTriageAction.MONITOR_INTERNAL,
                InternalTriageAction.QUEUE_INTERNAL,
            }:
                raise ValueError("Autonomous triage actions must remain internal.")
            if not self.reversible or self.requires_human_intervention:
                raise ValueError(
                    "Autonomous internal triage must be reversible and "
                    "intervention-free."
                )
        if self.priority == IncidentPriority.CRITICAL and (
            self.action != InternalTriageAction.ESCALATE_CRITICAL
            or self.autonomy_mode != TriageAutonomyMode.HUMAN_IN_THE_LOOP
            or not self.requires_human_intervention
        ):
            raise ValueError("Critical incidents require human-in-the-loop escalation.")


MIN_WATCH_REFRESH_SECONDS = 300
MAX_WATCH_REFRESH_SECONDS = 86_400


class WatchScopeKind(StrEnum):
    COUNTRY = "country"
    WORLDWIDE = "worldwide"


class WatchCoverageState(StrEnum):
    EVENTS_FOUND = "events_found"
    NO_MATCHING_RECORDS = "no_matching_records"
    STALE = "stale"
    DEGRADED = "degraded"
    UNAVAILABLE = "unavailable"


class IncidentChangeKind(StrEnum):
    NEW_EVENT = "new_event"
    OBSERVATION_GAP = "observation_gap"
    MEASUREMENTS_CHANGED = "measurements_changed"
    GEOMETRY_CHANGED = "geometry_changed"
    EVIDENCE_SET_CHANGED = "evidence_set_changed"
    COVERAGE_CHANGED = "coverage_changed"


@dataclass(frozen=True, slots=True)
class IncidentWatchScope:
    kind: WatchScopeKind
    country_code: str | None = None
    country_name: str | None = None

    def __post_init__(self) -> None:
        if self.kind is WatchScopeKind.WORLDWIDE:
            if self.country_code is not None or self.country_name is not None:
                raise ValueError("Worldwide watch scope cannot include a country.")
            return
        if (
            self.country_code is None
            or len(self.country_code) != 3
            or not self.country_code.isupper()
            or self.country_name is None
            or not self.country_name.strip()
        ):
            raise ValueError("Country watch scope requires one canonical country.")

    @classmethod
    def worldwide(cls) -> IncidentWatchScope:
        return cls(WatchScopeKind.WORLDWIDE)

    @classmethod
    def country(cls, code: str, name: str) -> IncidentWatchScope:
        return cls(WatchScopeKind.COUNTRY, code, name)

    @property
    def display_name(self) -> str:
        return self.country_name or "Worldwide"


@dataclass(frozen=True, slots=True)
class IncidentWatch:
    watch_id: str
    disaster: Disaster
    scope: IncidentWatchScope
    enabled: bool
    refresh_interval_seconds: int
    created_at: datetime
    updated_at: datetime
    next_refresh_at: datetime
    last_checked_at: datetime | None = None
    coverage_state: WatchCoverageState | None = None
    unread_change_count: int = 0

    def __post_init__(self) -> None:
        if not self.watch_id.strip():
            raise ValueError("Incident watches require a stable identifier.")
        if not isinstance(self.disaster, Disaster):
            raise TypeError("Incident watches require one supported disaster type.")
        if isinstance(self.refresh_interval_seconds, bool) or not (
            MIN_WATCH_REFRESH_SECONDS
            <= self.refresh_interval_seconds
            <= MAX_WATCH_REFRESH_SECONDS
        ):
            raise ValueError(
                "Watch refresh interval must be between 300 and 86400 seconds."
            )
        for value in (self.created_at, self.updated_at, self.next_refresh_at):
            _require_aware(value, "Incident watch times must be timezone-aware.")
        if self.last_checked_at is not None:
            _require_aware(
                self.last_checked_at,
                "Incident watch times must be timezone-aware.",
            )
        if self.unread_change_count < 0:
            raise ValueError("Unread watch change count cannot be negative.")


@dataclass(frozen=True, slots=True)
class WatchIncident:
    physical_event_id: str
    event_id: str
    disaster: Disaster
    location: str
    event_time: datetime
    geometry: EventGeometry | None
    measurements: tuple[EventMeasurement, ...]
    provider_ids: tuple[str, ...]
    provider_tier: ProviderTier
    source_authority: SourceAuthority
    source: SourceReference
    evidence_sources: tuple[SourceReference, ...]

    def __post_init__(self) -> None:
        if not self.physical_event_id.strip() or not self.event_id.strip():
            raise ValueError("Watched incidents require stable event identity.")
        if not self.location.strip():
            raise ValueError("Watched incidents require a source-backed location.")
        _require_aware(self.event_time, "Watched incident time must be timezone-aware.")
        if self.source not in self.evidence_sources:
            raise ValueError(
                "Watched incident evidence must include its primary source."
            )

    @classmethod
    def from_source_evidence(
        cls,
        *,
        event_id: str,
        disaster: Disaster,
        location: str,
        event_time: datetime,
        geometry: EventGeometry | None,
        measurements: tuple[EventMeasurement, ...],
        provider_ids: tuple[str, ...],
        provider_tier: ProviderTier,
        source_authority: SourceAuthority,
        source: SourceReference,
        evidence_sources: tuple[SourceReference, ...],
        physical_event_id: str | None = None,
    ) -> WatchIncident:
        sources = {
            source,
            *(item.source for item in measurements),
            *((geometry.source,) if geometry is not None else ()),
            *evidence_sources,
        }
        ordered_sources = tuple(sorted(sources, key=_source_order_key))
        stable_id = physical_event_id or _stable_physical_event_id(
            disaster, source.source_id, event_id
        )
        return cls(
            physical_event_id=stable_id,
            event_id=event_id,
            disaster=disaster,
            location=location,
            event_time=event_time,
            geometry=geometry,
            measurements=tuple(sorted(measurements, key=_measurement_order_key)),
            provider_ids=tuple(sorted(set(provider_ids))),
            provider_tier=provider_tier,
            source_authority=source_authority,
            source=source,
            evidence_sources=ordered_sources,
        )

    @property
    def source_ids(self) -> tuple[str, ...]:
        return tuple(sorted({item.source_id for item in self.evidence_sources}))

    @property
    def geometry_hash(self) -> str:
        return canonical_hash(geometry_document(self.geometry))

    @property
    def measurements_hash(self) -> str:
        return canonical_hash(
            [measurement_document(item) for item in self.measurements]
        )

    @property
    def evidence_hash(self) -> str:
        return canonical_hash(
            {
                "provider_ids": self.provider_ids,
                "sources": [
                    source_evidence_document(item) for item in self.evidence_sources
                ],
            }
        )

    @property
    def state_hash(self) -> str:
        return canonical_hash(watch_incident_document(self))


@dataclass(frozen=True, slots=True)
class IncidentWatchObservation:
    observation_id: str
    watch_id: str
    observed_at: datetime
    coverage_state: WatchCoverageState
    incidents: tuple[WatchIncident, ...]
    provider_names: tuple[str, ...]
    warnings: tuple[str, ...]
    state_hash: str
    successful: bool
    retryable: bool = False
    provider_source_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.observation_id.strip() or not self.watch_id.strip():
            raise ValueError("Watch observations require stable identity.")
        _require_aware(
            self.observed_at, "Watch observation time must be timezone-aware."
        )
        if not _valid_prefixed_sha256(self.state_hash):
            raise ValueError("Watch observation state must have a SHA-256 identity.")

    @classmethod
    def create(
        cls,
        *,
        watch_id: str,
        observed_at: datetime,
        coverage_state: WatchCoverageState,
        incidents: tuple[WatchIncident, ...],
        provider_names: tuple[str, ...],
        warnings: tuple[str, ...],
        successful: bool,
        retryable: bool = False,
        provider_source_ids: tuple[str, ...] = (),
    ) -> IncidentWatchObservation:
        ordered_incidents = tuple(
            sorted(
                incidents,
                key=lambda item: (
                    item.physical_event_id,
                    item.event_time,
                    item.event_id,
                ),
            )
        )
        document = {
            "coverage_state": coverage_state.value,
            "incidents": [watch_incident_document(item) for item in ordered_incidents],
            "provider_names": sorted(set(provider_names)),
            "provider_source_ids": sorted(set(provider_source_ids)),
            "successful": successful,
            "retryable": retryable,
        }
        state_hash = canonical_hash(document)
        return cls(
            observation_id=(
                "incident-watch-observation:"
                + hashlib.sha256(f"{watch_id}|{state_hash}".encode()).hexdigest()[:24]
            ),
            watch_id=watch_id,
            observed_at=observed_at,
            coverage_state=coverage_state,
            incidents=ordered_incidents,
            provider_names=tuple(sorted(set(provider_names))),
            warnings=tuple(dict.fromkeys(warnings)),
            state_hash=state_hash,
            successful=successful,
            retryable=retryable,
            provider_source_ids=tuple(sorted(set(provider_source_ids))),
        )


@dataclass(frozen=True, slots=True)
class IncidentWatchChange:
    change_id: str
    watch_id: str
    kind: IncidentChangeKind
    summary: str
    detail: str
    created_at: datetime
    source_ids: tuple[str, ...]
    observation_id: str
    previous_observation_id: str | None
    before_hash: str | None
    after_hash: str | None
    incident: WatchIncident | None = None
    read_at: datetime | None = None

    def __post_init__(self) -> None:
        if not self.change_id.strip() or not self.watch_id.strip():
            raise ValueError("Watch changes require stable identity.")
        if not self.summary.strip() or not self.detail.strip():
            raise ValueError("Watch changes require an auditable description.")
        _require_aware(self.created_at, "Watch change time must be timezone-aware.")
        if self.read_at is not None:
            _require_aware(self.read_at, "Watch read time must be timezone-aware.")

    @classmethod
    def create(
        cls,
        *,
        watch: IncidentWatch,
        kind: IncidentChangeKind,
        current: IncidentWatchObservation,
        previous: IncidentWatchObservation | None,
        summary: str,
        detail: str,
        incident: WatchIncident | None,
        before_hash: str | None,
        after_hash: str | None,
        source_ids: tuple[str, ...],
    ) -> IncidentWatchChange:
        physical_event_id = incident.physical_event_id if incident is not None else ""
        material = "|".join(
            (
                watch.watch_id,
                kind.value,
                previous.observation_id if previous is not None else "",
                current.observation_id,
                current.observed_at.isoformat(),
                physical_event_id,
                before_hash or "",
                after_hash or "",
            )
        )
        return cls(
            change_id=(
                "incident-watch-change:"
                + hashlib.sha256(material.encode("utf-8")).hexdigest()[:24]
            ),
            watch_id=watch.watch_id,
            kind=kind,
            summary=summary,
            detail=detail,
            created_at=current.observed_at,
            source_ids=tuple(sorted(set(source_ids))),
            observation_id=current.observation_id,
            previous_observation_id=(
                previous.observation_id if previous is not None else None
            ),
            before_hash=before_hash,
            after_hash=after_hash,
            incident=incident,
        )

    @classmethod
    def create_coverage_change(
        cls,
        *,
        watch: IncidentWatch,
        previous: IncidentWatchObservation | None,
        current: IncidentWatchObservation,
    ) -> IncidentWatchChange:
        previous_label = (
            previous.coverage_state.value if previous is not None else "not_checked"
        )
        source_ids = tuple(
            sorted(
                {
                    source_id
                    for observation in (previous, current)
                    if observation is not None
                    for source_id in observation.provider_source_ids
                }
                | {
                    source_id
                    for observation in (previous, current)
                    if observation is not None
                    for incident in observation.incidents
                    for source_id in incident.source_ids
                }
            )
        )
        return cls.create(
            watch=watch,
            kind=IncidentChangeKind.COVERAGE_CHANGED,
            current=current,
            previous=previous,
            summary="Watch coverage changed",
            detail=(
                f"Bounded provider coverage changed from {previous_label} to "
                f"{current.coverage_state.value}."
            ),
            incident=None,
            before_hash=(
                canonical_hash(previous_label) if previous is not None else None
            ),
            after_hash=canonical_hash(current.coverage_state.value),
            source_ids=source_ids,
        )

    def mark_read(self, read_at: datetime) -> IncidentWatchChange:
        return replace(self, read_at=read_at)


def canonical_hash(value: object) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def watch_incident_document(value: WatchIncident) -> dict[str, object]:
    return {
        "physical_event_id": value.physical_event_id,
        "event_id": value.event_id,
        "disaster": value.disaster.value,
        "location": value.location,
        "event_time": value.event_time.isoformat(),
        "geometry": geometry_document(value.geometry),
        "measurements": [measurement_document(item) for item in value.measurements],
        "provider_ids": list(value.provider_ids),
        "provider_tier": value.provider_tier.value,
        "source_authority": value.source_authority.value,
        "source": source_document(value.source),
        "evidence_sources": [source_document(item) for item in value.evidence_sources],
    }


def watch_incident_from_document(value: object) -> WatchIncident:
    item = _mapping(value)
    source_value = source_from_document(item["source"])
    evidence_sources = tuple(
        source_from_document(entry)
        for entry in cast(list[object], item.get("evidence_sources", []))
    )
    sources_by_id = {
        source.source_id: source for source in (source_value, *evidence_sources)
    }
    return WatchIncident.from_source_evidence(
        physical_event_id=str(item["physical_event_id"]),
        event_id=str(item["event_id"]),
        disaster=Disaster(str(item["disaster"])),
        location=str(item["location"]),
        event_time=datetime.fromisoformat(str(item["event_time"])),
        geometry=geometry_from_document(item.get("geometry"), sources_by_id),
        measurements=tuple(
            measurement_from_document(entry, sources_by_id)
            for entry in cast(list[object], item.get("measurements", []))
        ),
        provider_ids=tuple(str(entry) for entry in item.get("provider_ids", [])),
        provider_tier=ProviderTier(str(item["provider_tier"])),
        source_authority=SourceAuthority(str(item["source_authority"])),
        source=source_value,
        evidence_sources=evidence_sources,
    )


def source_document(value: SourceReference) -> dict[str, object]:
    return {
        "source_id": value.source_id,
        "publisher": value.publisher,
        "title": value.title,
        "canonical_url": value.canonical_url,
        "published_at": _optional_datetime(value.published_at),
        "updated_at": _optional_datetime(value.updated_at),
        "retrieved_at": value.retrieved_at.isoformat(),
        "authority": value.authority.value,
        "snapshot_id": value.snapshot_id,
    }


def source_evidence_document(value: SourceReference) -> dict[str, object]:
    document = source_document(value)
    document.pop("retrieved_at")
    return document


def source_from_document(value: object) -> SourceReference:
    item = _mapping(value)
    return SourceReference(
        source_id=str(item["source_id"]),
        publisher=str(item["publisher"]),
        title=str(item["title"]),
        canonical_url=str(item["canonical_url"]),
        published_at=_parse_optional_datetime(item.get("published_at")),
        updated_at=_parse_optional_datetime(item.get("updated_at")),
        retrieved_at=datetime.fromisoformat(str(item["retrieved_at"])),
        authority=SourceAuthority(str(item["authority"])),
        snapshot_id=(str(item["snapshot_id"]) if item.get("snapshot_id") else None),
    )


def geometry_document(value: EventGeometry | None) -> dict[str, object] | None:
    if value is None:
        return None
    return {
        "kind": value.kind.value,
        "coordinates": [
            {"latitude": item.latitude, "longitude": item.longitude}
            for item in value.coordinates
        ],
        "description": value.description,
        "source_id": value.source.source_id,
        "estimated": value.estimated,
    }


def geometry_from_document(
    value: object, sources_by_id: dict[str, SourceReference]
) -> EventGeometry | None:
    if value is None:
        return None
    item = _mapping(value)
    source = _document_source(item, sources_by_id)
    return EventGeometry(
        kind=EventGeometryKind(str(item["kind"])),
        source=source,
        coordinates=tuple(
            EventCoordinate(
                float(_mapping(entry)["latitude"]),
                float(_mapping(entry)["longitude"]),
            )
            for entry in cast(list[object], item.get("coordinates", []))
        ),
        description=(str(item["description"]) if item.get("description") else None),
        estimated=bool(item.get("estimated", False)),
    )


def measurement_document(value: EventMeasurement) -> dict[str, object]:
    return {
        "kind": value.kind.value,
        "value": value.value,
        "unit": value.unit,
        "source_id": value.source.source_id,
    }


def measurement_from_document(
    value: object, sources_by_id: dict[str, SourceReference]
) -> EventMeasurement:
    item = _mapping(value)
    source = _document_source(item, sources_by_id)
    return EventMeasurement(
        MeasurementKind(str(item["kind"])),
        cast(float | str, item["value"]),
        str(item["unit"]) if item.get("unit") is not None else None,
        source=source,
    )


def _document_source(
    item: dict[str, Any], sources_by_id: dict[str, SourceReference]
) -> SourceReference:
    source_id = str(item["source_id"])
    try:
        return sources_by_id[source_id]
    except KeyError as error:
        raise ValueError(
            f"Watch incident references unknown evidence source {source_id!r}."
        ) from error


def _stable_physical_event_id(disaster: Disaster, source_id: str, event_id: str) -> str:
    material = f"{disaster.value}|{source_id.casefold()}|{event_id.casefold()}"
    return "watch-event:" + hashlib.sha256(material.encode("utf-8")).hexdigest()[:24]


def _source_order_key(value: SourceReference) -> tuple[str, str, str, str]:
    return (
        value.source_id,
        value.canonical_url,
        _optional_datetime(value.updated_at) or "",
        value.snapshot_id or "",
    )


def _measurement_order_key(
    value: EventMeasurement,
) -> tuple[str, str, str, str]:
    return (
        value.kind.value,
        str(value.value),
        value.unit or "",
        value.source.source_id,
    )


def _optional_datetime(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _parse_optional_datetime(value: object) -> datetime | None:
    return datetime.fromisoformat(str(value)) if value is not None else None


def _mapping(value: object) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("Watch incident document must be an object.")
    return cast(dict[str, Any], value)


def _require_aware(value: datetime, message: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(message)


def _valid_prefixed_sha256(value: str) -> bool:
    prefix, separator, digest = value.partition(":")
    if prefix != "sha256" or separator != ":" or len(digest) != 64:
        return False
    try:
        int(digest, 16)
    except ValueError:
        return False
    return True
