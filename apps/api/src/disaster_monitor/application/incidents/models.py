"""Bounded provider-backed discovery for the Active Incidents surface."""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from disaster_monitor.application.disaster import ObservationKind
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
    IncidentActivityStatus,
    ProviderTier,
    SourceAuthority,
    SourceReference,
)
from disaster_monitor.domain.operations import ProviderAttempt


class IncidentView(StrEnum):
    """Temporal interpretation of an incident query."""

    RECENT = "recent"
    ONGOING = "ongoing"
    RECENTLY_UPDATED = "recently_updated"
    HISTORICAL = "historical"


@dataclass(frozen=True, slots=True)
class ActiveIncidentsQuery:
    """Operator-controlled bounds for one all-hazard retrieval."""

    time_window_days: int = 7
    limit_per_disaster: int = 10
    acquisition_limit_per_disaster: int = 100
    view: IncidentView = IncidentView.RECENT
    hazard: Disaster | None = None
    country_code: str | None = None
    search: str | None = None
    page_size: int | None = None
    cursor: str | None = None

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
        if (
            isinstance(self.acquisition_limit_per_disaster, bool)
            or not isinstance(self.acquisition_limit_per_disaster, int)
            or not 1 <= self.acquisition_limit_per_disaster <= 500
        ):
            raise ValueError(
                "acquisition_limit_per_disaster must be between 1 and 500."
            )
        if not isinstance(self.view, IncidentView):
            raise ValueError("view must be a supported incident view.")
        if self.country_code is not None:
            normalized_country = self.country_code.strip().upper()
            if len(normalized_country) != 3 or not normalized_country.isalpha():
                raise ValueError("country_code must be a three-letter ISO code.")
            object.__setattr__(self, "country_code", normalized_country)
        if self.search is not None:
            normalized_search = self.search.strip()
            object.__setattr__(self, "search", normalized_search or None)
        if self.page_size is not None and not 1 <= self.page_size <= 100:
            raise ValueError("page_size must be between 1 and 100.")
        if self.cursor is not None and not self.cursor.strip():
            raise ValueError("cursor must not be empty.")


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
    country: IncidentCountryAssociation | None
    location: str
    event_time: datetime
    geometry: EventGeometry | None
    measurements: tuple[EventMeasurement, ...]
    provider_ids: tuple[str, ...]
    provider_tier: ProviderTier
    source_authority: SourceAuthority
    source: SourceReference
    lineage_ids: tuple[str, ...] = ()
    physical_event_id: str | None = None
    evidence_sources: tuple[SourceReference, ...] = ()
    observation_kind: ObservationKind = ObservationKind.PHYSICAL_EVENT
    activity_status: IncidentActivityStatus = IncidentActivityStatus.UNKNOWN


@dataclass(frozen=True, slots=True)
class DisasterIncidentCoverage:
    """Per-disaster retrieval result, separate from factual event claims."""

    disaster: Disaster
    state: IncidentCoverageState
    incident_count: int
    providers: tuple[str, ...]
    detail: str
    scan_complete: bool = True
    records_seen: int = 0
    truncated: bool = False


@dataclass(frozen=True, slots=True)
class ActiveIncidentsSnapshot:
    """Bounded all-hazard incident list and its explicit coverage state."""

    retrieved_at: datetime
    incidents: tuple[ActiveIncident, ...]
    coverage: tuple[DisasterIncidentCoverage, ...]
    warnings: tuple[str, ...]
    observations: tuple[ActiveIncident, ...] = ()
    correlations: tuple[CompoundHazardCorrelation, ...] = ()
    snapshot_version: str | None = None
    next_cursor: str | None = None
    has_more: bool = False
    total_incident_count: int | None = None


@dataclass(frozen=True, slots=True)
class IncidentRetrievalResult:
    incidents: tuple[ActiveIncident, ...]
    coverage: DisasterIncidentCoverage
    warnings: tuple[str, ...]
    observations: tuple[ActiveIncident, ...] = ()
    successful: bool = True
    retryable: bool = False
    provider_source_ids: tuple[str, ...] = ()
    provider_attempts: tuple[ProviderAttempt, ...] = ()
