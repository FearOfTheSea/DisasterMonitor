"""Canonical reports, observations, and evidence-world state."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from disaster_monitor.domain.disaster_types import Disaster
from disaster_monitor.domain.events import (
    CycloneMapLayer,
    EventMeasurement,
    PhysicalEventIdentity,
)
from disaster_monitor.domain.evidence_types import (
    CorrelationStatus,
    EvidenceAvailability,
    EvidenceDisposition,
    EvidenceFreshness,
    FactStatus,
    SourceReference,
)


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
    supplemental_geometry: tuple[CycloneMapLayer, ...] = ()


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
