"""Bounded provider-backed discovery for the Active Incidents surface."""

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum

from disaster_monitor.application.disaster import (
    ProviderBatch,
    WorldwideDisasterEvent,
    WorldwideDisasterQuery,
)
from disaster_monitor.application.services.provider_registry import (
    ProviderRegistration,
    ProviderRegistry,
    ProviderRole,
)
from disaster_monitor.application.services.source_evidence_policy import (
    SourceEvidencePolicyError,
    validate_worldwide_event_evidence,
)
from disaster_monitor.domain.disaster import (
    Disaster,
    EventGeometry,
    EventMeasurement,
    ProviderTier,
    SourceAuthority,
    SourceReference,
)


def _now_utc() -> datetime:
    return datetime.now(UTC)


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
    location: str
    event_time: datetime
    geometry: EventGeometry | None
    measurements: tuple[EventMeasurement, ...]
    provider_ids: tuple[str, ...]
    provider_tier: ProviderTier
    source_authority: SourceAuthority
    source: SourceReference


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


@dataclass(frozen=True, slots=True)
class _DisasterResult:
    incidents: tuple[ActiveIncident, ...]
    coverage: DisasterIncidentCoverage
    warnings: tuple[str, ...]


class ActiveIncidentsService:
    """Query registry-approved worldwide event providers without an LLM."""

    def __init__(
        self,
        provider_registry: ProviderRegistry,
        *,
        clock: Callable[[], datetime] = _now_utc,
    ) -> None:
        self._provider_registry = provider_registry
        self._clock = clock

    async def execute(
        self, query: ActiveIncidentsQuery | None = None
    ) -> ActiveIncidentsSnapshot:
        bounded_query = query or ActiveIncidentsQuery()
        now = self._clock()
        results = await asyncio.gather(
            *(
                self._retrieve_disaster(disaster, bounded_query, now=now)
                for disaster in Disaster
            )
        )
        incidents = tuple(
            sorted(
                (incident for result in results for incident in result.incidents),
                key=lambda incident: (
                    -incident.event_time.timestamp(),
                    incident.disaster.value,
                    incident.event_id,
                    incident.source.source_id,
                ),
            )
        )
        return ActiveIncidentsSnapshot(
            retrieved_at=now,
            incidents=incidents,
            coverage=tuple(result.coverage for result in results),
            warnings=tuple(
                dict.fromkeys(
                    warning for result in results for warning in result.warnings
                )
            ),
        )

    async def _retrieve_disaster(
        self,
        disaster: Disaster,
        query: ActiveIncidentsQuery,
        *,
        now: datetime,
    ) -> _DisasterResult:
        provider_query = WorldwideDisasterQuery(
            disaster=disaster,
            time_window_days=query.time_window_days,
            limit=query.limit_per_disaster,
        )
        selection = self._provider_registry.select(
            provider_query, ProviderRole.EVENT_DISCOVERY
        )
        if not selection.registrations:
            unavailable = tuple(selection.unavailable_configuration)
            return _DisasterResult(
                incidents=(),
                coverage=DisasterIncidentCoverage(
                    disaster=disaster,
                    state=IncidentCoverageState.UNAVAILABLE,
                    incident_count=0,
                    providers=unavailable,
                    detail=(
                        "No configured worldwide event-discovery provider is "
                        "available for this disaster."
                    ),
                ),
                warnings=(),
            )

        accepted_by_tier: dict[ProviderTier, list[ActiveIncident]] = {}
        warnings: list[str] = []
        degraded = False
        for registration in selection.registrations:
            records, provider_warnings, provider_degraded = await self._query_provider(
                registration, provider_query, now=now
            )
            warnings.extend(provider_warnings)
            degraded = degraded or provider_degraded
            accepted_by_tier.setdefault(registration.tier, []).extend(records)

        highest_tier = max(
            (tier for tier, records in accepted_by_tier.items() if records),
            key=lambda tier: tier.precedence,
            default=None,
        )
        retained = (
            tuple(
                sorted(
                    accepted_by_tier[highest_tier],
                    key=lambda incident: (
                        -incident.event_time.timestamp(),
                        incident.event_id,
                        incident.source.source_id,
                    ),
                )[: query.limit_per_disaster]
            )
            if highest_tier is not None
            else ()
        )
        state = (
            IncidentCoverageState.DEGRADED
            if degraded
            else IncidentCoverageState.EVENTS_FOUND
            if retained
            else IncidentCoverageState.NO_MATCHING_RECORDS
        )
        return _DisasterResult(
            incidents=retained,
            coverage=DisasterIncidentCoverage(
                disaster=disaster,
                state=state,
                incident_count=len(retained),
                providers=tuple(item.name for item in selection.registrations),
                detail=_coverage_detail(state, len(retained)),
            ),
            warnings=tuple(dict.fromkeys(warnings)),
        )

    async def _query_provider(
        self,
        registration: ProviderRegistration,
        query: WorldwideDisasterQuery,
        *,
        now: datetime,
    ) -> tuple[tuple[ActiveIncident, ...], tuple[str, ...], bool]:
        provider = registration.worldwide_provider
        if (
            not registration.source_id
            or not registration.allowed_hosts
            or provider is None
        ):
            return (
                (),
                (
                    f"Worldwide provider {registration.name} has incomplete "
                    "executable authority.",
                ),
                True,
            )
        try:
            raw_batch = await provider.find_worldwide_events(query, now=now)
            batch = (
                raw_batch
                if isinstance(raw_batch, ProviderBatch)
                else ProviderBatch(tuple(raw_batch))
            )
        except Exception:
            return (
                (),
                (
                    f"Worldwide provider {registration.name} could not be reached "
                    "or returned invalid data.",
                ),
                True,
            )

        accepted: list[ActiveIncident] = []
        warnings: list[str] = []
        degraded = False
        for record in batch.records:
            try:
                event = validate_worldwide_event_evidence(
                    record,
                    query,
                    source_id=registration.source_id,
                    allowed_hosts=registration.allowed_hosts,
                )
            except SourceEvidencePolicyError:
                warnings.append(
                    "A worldwide disaster record violated source policy and was "
                    "excluded."
                )
                degraded = True
                continue
            accepted.append(_incident(event, registration.tier))
        for issue in batch.issues:
            if issue.reason_code == "empty_result":
                continue
            warnings.append(issue.message)
            degraded = True
        return tuple(accepted), tuple(dict.fromkeys(warnings)), degraded


def _incident(
    event: WorldwideDisasterEvent, provider_tier: ProviderTier
) -> ActiveIncident:
    return ActiveIncident(
        event_id=event.event_id,
        disaster=event.disaster,
        location=event.location,
        event_time=event.event_time,
        geometry=event.geometry,
        measurements=event.measurements,
        provider_ids=event.provider_ids,
        provider_tier=provider_tier,
        source_authority=event.source.authority,
        source=event.source,
    )


def _coverage_detail(state: IncidentCoverageState, incident_count: int) -> str:
    if state is IncidentCoverageState.EVENTS_FOUND:
        return (
            f"{incident_count} usable event record(s) were returned from the "
            "highest provider tier with evidence."
        )
    if state is IncidentCoverageState.NO_MATCHING_RECORDS:
        return (
            "Configured providers completed successfully but returned no usable "
            "matching records. This is not evidence that no disaster occurred."
        )
    return (
        "Usable records may be incomplete because a provider failed or returned "
        "evidence that could not be admitted."
    )
