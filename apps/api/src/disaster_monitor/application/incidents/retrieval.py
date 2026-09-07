"""Bounded provider-backed discovery for the Active Incidents surface."""

from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from disaster_monitor.application.disaster import (
    DisasterQuery,
    ProviderBatch,
    WorldwideDisasterEvent,
    WorldwideDisasterQuery,
)
from disaster_monitor.application.evidence.event_resolution import (
    EventPolicyRegistry,
    default_event_policy_registry,
)
from disaster_monitor.application.evidence.source_evidence_policy import (
    validate_worldwide_event_evidence,
)
from disaster_monitor.application.incidents.models import (
    ActiveIncident,
    ActiveIncidentsQuery,
    DisasterIncidentCoverage,
    IncidentCoverageState,
    IncidentRetrievalResult,
)
from disaster_monitor.application.ports.disaster_information import (
    DisasterEventProvider,
)
from disaster_monitor.application.ports.geography import CountryCatalog
from disaster_monitor.application.ports.source_evidence import (
    SourceEvidencePolicyError,
)
from disaster_monitor.application.sources.provider_registry import (
    ProviderRegistration,
    ProviderRegistry,
    ProviderRole,
)
from disaster_monitor.domain.disaster import (
    Disaster,
    IncidentWatch,
    PhysicalEventIdentity,
    ProviderTier,
)


def _now_utc() -> datetime:
    return datetime.now(UTC)


class IncidentRetrieval:
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

    async def country(
        self,
        watch: IncidentWatch,
        query: ActiveIncidentsQuery,
        *,
        now: datetime,
    ) -> IncidentRetrievalResult:
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
            return IncidentRetrievalResult(
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
        return IncidentRetrievalResult(
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

    async def worldwide(
        self,
        disaster: Disaster,
        query: ActiveIncidentsQuery,
        *,
        now: datetime,
    ) -> IncidentRetrievalResult:
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
            return IncidentRetrievalResult(
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
        return IncidentRetrievalResult(
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
            accepted.append(
                _incident(
                    event,
                    registration.tier,
                    country_catalog=self._country_catalog,
                )
            )
        for issue in batch.issues:
            if issue.reason_code == "empty_result":
                continue
            warnings.append(issue.message)
            degraded = True
            retryable = retryable or issue.retryable
        return tuple(accepted), tuple(dict.fromkeys(warnings)), degraded, retryable


def _incident(
    event: WorldwideDisasterEvent,
    provider_tier: ProviderTier,
    *,
    country_catalog: CountryCatalog | None,
) -> ActiveIncident:
    return ActiveIncident(
        event_id=event.event_id,
        disaster=event.disaster,
        location=_country_or_location(event, country_catalog),
        event_time=event.event_time,
        geometry=event.geometry,
        measurements=event.measurements,
        provider_ids=event.provider_ids,
        provider_tier=provider_tier,
        source_authority=event.source.authority,
        source=event.source,
        evidence_sources=(event.source,),
    )


def _country_or_location(
    event: WorldwideDisasterEvent,
    country_catalog: CountryCatalog | None,
) -> str:
    """Prefer one catalog country, then preserve an explicit source location."""
    if country_catalog is not None:
        if event.geometry is not None and event.geometry.coordinates:
            coordinate = event.geometry.coordinates[0]
            for country in country_catalog.countries():
                if country_catalog.contains(
                    country, coordinate.latitude, coordinate.longitude
                ):
                    return country.canonical_name
        mentioned_countries = country_catalog.find_mentions(event.location)
        if mentioned_countries:
            return mentioned_countries[0].canonical_name
    return event.location


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


def _unavailable_country_result(
    watch: IncidentWatch, providers: tuple[str, ...] = ()
) -> IncidentRetrievalResult:
    return IncidentRetrievalResult(
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
