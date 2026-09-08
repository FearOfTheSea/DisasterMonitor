"""Bounded provider-backed discovery for the Active Incidents surface."""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from disaster_monitor.application.evidence.event_policies import (
    CompoundHazardCorrelation,
)
from disaster_monitor.application.incidents.country_association import (
    IncidentCountryAssociation,
)
from disaster_monitor.domain.disaster import (
    Disaster,
    EventGeometry,
    EventMeasurement,
    ProviderTier,
    SourceAuthority,
    SourceReference,
)


@dataclass(frozen=True, slots=True)
class ActiveIncidentsQuery:
    """Operator-controlled bounds for one all-hazard retrieval."""

    time_window_days: int = 7
    limit_per_disaster: int = 10

    def __post_init__(self) -> None:
        if (
            isinstance(self.time_window_days, bool)
            or not isinstance(self.time_window_days, int)
            or not 1 <= self.time_window_days <= 30
        ):
            raise ValueError("time_window_days must be between 1 and 30.")
        if (
            isinstance(self.limit_per_disaster, bool)
            or not isinstance(self.limit_per_disaster, int)
            or not 1 <= self.limit_per_disaster <= 20
        ):
            raise ValueError("limit_per_disaster must be between 1 and 20.")


class IncidentCoverageState(StrEnum):
    """Honest outcome of one disaster-specific provider lookup."""

    EVENTS_FOUND = "events_found"
    NO_MATCHING_RECORDS = "no_matching_records"
    DEGRADED = "degraded"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True, slots=True)
class ActiveIncident:
    """One worldwide event retained with its exact source-backed evidence."""

    event_id: str
    disaster: Disaster
    country: IncidentCountryAssociation
    location: str
    event_time: datetime
    geometry: EventGeometry | None
    measurements: tuple[EventMeasurement, ...]
    provider_ids: tuple[str, ...]
    provider_tier: ProviderTier
    source_authority: SourceAuthority
    source: SourceReference
    physical_event_id: str | None = None
    evidence_sources: tuple[SourceReference, ...] = ()


@dataclass(frozen=True, slots=True)
class DisasterIncidentCoverage:
    """Per-disaster retrieval result, separate from factual event claims."""

    disaster: Disaster
    state: IncidentCoverageState
    incident_count: int
    providers: tuple[str, ...]
    detail: str


@dataclass(frozen=True, slots=True)
class ActiveIncidentsSnapshot:
    """Bounded all-hazard incident list and its explicit coverage state."""

    retrieved_at: datetime
    incidents: tuple[ActiveIncident, ...]
    coverage: tuple[DisasterIncidentCoverage, ...]
    warnings: tuple[str, ...]
    correlations: tuple[CompoundHazardCorrelation, ...] = ()


@dataclass(frozen=True, slots=True)
class IncidentRetrievalResult:
    incidents: tuple[ActiveIncident, ...]
    coverage: DisasterIncidentCoverage
    warnings: tuple[str, ...]
    successful: bool = True
    retryable: bool = False
    provider_source_ids: tuple[str, ...] = ()
