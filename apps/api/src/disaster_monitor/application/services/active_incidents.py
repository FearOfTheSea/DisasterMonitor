"""Bounded provider-backed discovery for the Active Incidents surface."""

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum

from disaster_monitor.application.disaster import (
    DisasterQuery,
    ProviderBatch,
    WorldwideDisasterEvent,
    WorldwideDisasterQuery,
)
from disaster_monitor.application.ports.disaster_information import (
    DisasterEventProvider,
)
from disaster_monitor.application.ports.geography import CountryCatalog
from disaster_monitor.application.ports.source_evidence import (
    SourceEvidencePolicyError,
)
from disaster_monitor.application.services.event_resolution import (
    EventPolicyRegistry,
    default_event_policy_registry,
)
from disaster_monitor.application.services.evidence_state import source_is_stale
from disaster_monitor.application.services.provider_registry import (
    ProviderRegistration,
    ProviderRegistry,
    ProviderRole,
)
from disaster_monitor.application.services.source_evidence_policy import (
    validate_worldwide_event_evidence,
)
from disaster_monitor.domain.disaster import (
    Disaster,
    EventGeometry,
    EventMeasurement,
    IncidentWatch,
    IncidentWatchObservation,
    PhysicalEventIdentity,
    ProviderTier,
    SourceAuthority,
    SourceReference,
    WatchCoverageState,
    WatchIncident,
    WatchScopeKind,
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


@dataclass(frozen=True, slots=True)
class _DisasterResult:
    incidents: tuple[ActiveIncident, ...]
    coverage: DisasterIncidentCoverage
    warnings: tuple[str, ...]
    successful: bool = True
    retryable: bool = False
    provider_source_ids: tuple[str, ...] = ()


class ActiveIncidentsService:
    """Query registry-approved worldwide event providers without an LLM."""

    def __init__(
        self,
        provider_registry: ProviderRegistry,
        *,
        clock: Callable[[], datetime] = _now_utc,
        country_event_provider: DisasterEventProvider | None = None,
        country_catalog: CountryCatalog | None = None,
        event_policies: EventPolicyRegistry | None = None,
    ) -> None:
        self._provider_registry = provider_registry
        self._clock = clock
        self._country_event_provider = country_event_provider
        self._country_catalog = country_catalog
        self._event_policies = event_policies or default_event_policy_registry()

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

    async def observe_watch(self, watch: IncidentWatch) -> IncidentWatchObservation:
        """Observe one watch through the same bounded registered-provider path."""
        now = self._clock()
        query = ActiveIncidentsQuery()
        result = (
            await self._retrieve_disaster(watch.disaster, query, now=now)
            if watch.scope.kind is WatchScopeKind.WORLDWIDE
            else await self._retrieve_country(watch, query, now=now)
        )
        coverage = WatchCoverageState(result.coverage.state.value)
        if (
            coverage is WatchCoverageState.EVENTS_FOUND
            and result.incidents
            and any(
                source_is_stale(item.source.effective_at, now)
                for item in result.incidents
            )
        ):
            coverage = WatchCoverageState.STALE
        incidents = tuple(_watched_incident(item) for item in result.incidents)
        return IncidentWatchObservation.create(
            watch_id=watch.watch_id,
            observed_at=now,
            coverage_state=coverage,
            incidents=incidents,
            provider_names=result.coverage.providers,
            warnings=result.warnings,
            successful=(result.successful and coverage is not WatchCoverageState.STALE),
            retryable=result.retryable,
            provider_source_ids=result.provider_source_ids,
        )

    async def _retrieve_country(
        self,
        watch: IncidentWatch,
        query: ActiveIncidentsQuery,
        *,
        now: datetime,
    ) -> _DisasterResult:
        if self._country_event_provider is None or self._country_catalog is None:
            return _unavailable_country_result(watch)
        country_code = watch.scope.country_code
        country = (
            self._country_catalog.get_by_alpha3(country_code)
            if country_code is not None
            else None
        )
        if country is None:
            return _unavailable_country_result(watch)
        provider_query = DisasterQuery(
            disaster=watch.disaster,
            country=country,
            time_intent="incident_watch",
            focus=("event_overview",),
            time_window_days=query.time_window_days,
        )
        selection = self._provider_registry.select(
            provider_query, ProviderRole.EVENT_DISCOVERY
        )
        if not selection.registrations:
            return _unavailable_country_result(
                watch, selection.unavailable_configuration
            )
        try:
            raw_batch = await self._country_event_provider.find_recent_events(
                provider_query, now=now
            )
            batch = (
                raw_batch
                if isinstance(raw_batch, ProviderBatch)
                else ProviderBatch(tuple(raw_batch))
            )
        except Exception:
            return _DisasterResult(
                incidents=(),
                coverage=DisasterIncidentCoverage(
                    disaster=watch.disaster,
                    state=IncidentCoverageState.DEGRADED,
                    incident_count=0,
                    providers=tuple(item.name for item in selection.registrations),
                    detail=_coverage_detail(IncidentCoverageState.DEGRADED, 0),
                ),
                warnings=("A configured event provider could not be queried.",),
                successful=False,
                retryable=True,
                provider_source_ids=tuple(
                    item.source_id for item in selection.registrations if item.source_id
                ),
            )
        policy = self._event_policies.for_disaster(watch.disaster)
        identities = policy.identify(batch.records).physical_events
        retained = tuple(
            sorted(
                (
                    _country_incident(identity)
                    for identity in identities
                    if identity.event.disaster is watch.disaster
                    and identity.event.country.alpha3_code == country.alpha3_code
                    and identity.event.event_time
                    >= now - timedelta(days=query.time_window_days)
                ),
                key=lambda item: (-item.event_time.timestamp(), item.event_id),
            )[: query.limit_per_disaster]
        )
        material_issues = tuple(
            issue for issue in batch.issues if issue.reason_code != "empty_result"
        )
        degraded = bool(material_issues)
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
                disaster=watch.disaster,
                state=state,
                incident_count=len(retained),
                providers=tuple(item.name for item in selection.registrations),
                detail=_coverage_detail(state, len(retained)),
            ),
            warnings=tuple(dict.fromkeys(issue.message for issue in material_issues)),
            successful=bool(retained) or not degraded,
            retryable=any(issue.retryable for issue in material_issues),
            provider_source_ids=tuple(
                item.source_id for item in selection.registrations if item.source_id
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
                successful=False,
            )

        accepted_by_tier: dict[ProviderTier, list[ActiveIncident]] = {}
        warnings: list[str] = []
        degraded = False
        retryable = False
        for registration in selection.registrations:
            (
                records,
                provider_warnings,
                provider_degraded,
                provider_retryable,
            ) = await self._query_provider(registration, provider_query, now=now)
            warnings.extend(provider_warnings)
            degraded = degraded or provider_degraded
            retryable = retryable or provider_retryable
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
            successful=bool(retained) or not degraded,
            retryable=retryable,
            provider_source_ids=tuple(
                item.source_id for item in selection.registrations if item.source_id
            ),
        )

    async def _query_provider(
        self,
        registration: ProviderRegistration,
        query: WorldwideDisasterQuery,
        *,
        now: datetime,
    ) -> tuple[tuple[ActiveIncident, ...], tuple[str, ...], bool, bool]:
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
                False,
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
                True,
            )

        accepted: list[ActiveIncident] = []
        warnings: list[str] = []
        degraded = False
        retryable = False
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
            retryable = retryable or issue.retryable
        return tuple(accepted), tuple(dict.fromkeys(warnings)), degraded, retryable


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
        evidence_sources=(event.source,),
    )


def _country_incident(identity: PhysicalEventIdentity) -> ActiveIncident:
    event = identity.event
    return ActiveIncident(
        event_id=event.event_id,
        disaster=event.disaster,
        location=event.location,
        event_time=event.event_time,
        geometry=event.geometry,
        measurements=event.measurements,
        provider_ids=event.provider_ids,
        provider_tier=event.provider_tier,
        source_authority=event.source.authority,
        source=event.source,
        physical_event_id=identity.physical_event_id,
        evidence_sources=tuple(
            sorted(
                {item.source for item in identity.observations},
                key=lambda item: (item.source_id, item.canonical_url),
            )
        ),
    )


def _watched_incident(value: ActiveIncident) -> WatchIncident:
    return WatchIncident.from_source_evidence(
        event_id=value.event_id,
        disaster=value.disaster,
        location=value.location,
        event_time=value.event_time,
        geometry=value.geometry,
        measurements=value.measurements,
        provider_ids=value.provider_ids,
        provider_tier=value.provider_tier,
        source_authority=value.source_authority,
        source=value.source,
        evidence_sources=value.evidence_sources or (value.source,),
        physical_event_id=value.physical_event_id,
    )


def _unavailable_country_result(
    watch: IncidentWatch, providers: tuple[str, ...] = ()
) -> _DisasterResult:
    return _DisasterResult(
        incidents=(),
        coverage=DisasterIncidentCoverage(
            disaster=watch.disaster,
            state=IncidentCoverageState.UNAVAILABLE,
            incident_count=0,
            providers=providers,
            detail=(
                "No configured country event-discovery provider is available for "
                "this watch."
            ),
        ),
        warnings=(),
        successful=False,
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
