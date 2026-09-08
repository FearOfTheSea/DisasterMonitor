"""Bounded provider-backed discovery for the Active Incidents surface."""

from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from disaster_monitor.application.disaster import (
    DisasterQuery,
    ObservationKind,
    ProviderBatch,
    WorldwideDisasterQuery,
)
from disaster_monitor.application.evidence.event_resolution import (
    EventPolicyRegistry,
    default_event_policy_registry,
)
from disaster_monitor.application.evidence.source_evidence_policy import (
    validate_worldwide_event_evidence,
)
from disaster_monitor.application.incidents.country_association import (
    IncidentCountryResolver,
)
from disaster_monitor.application.incidents.models import (
    ActiveIncident,
    ActiveIncidentsQuery,
    DisasterIncidentCoverage,
    IncidentCoverageState,
    IncidentRetrievalResult,
    IncidentView,
)
from disaster_monitor.application.incidents.retrieval_projection import (
    country_incident,
    country_observation,
    incident,
    resolve_worldwide_incidents,
)
from disaster_monitor.application.ports.disaster_information import (
    DisasterEventProvider,
)
from disaster_monitor.application.ports.geographic_regions import (
    GeographicRegionCatalog,
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
)
from disaster_monitor.domain.operations import ProviderAttempt, ProviderAttemptOutcome


def _now_utc() -> datetime:
    return datetime.now(UTC)


class IncidentRetrieval:
    def __init__(
        self,
        provider_registry: ProviderRegistry,
        *,
        country_catalog: CountryCatalog,
        clock: Callable[[], datetime] = _now_utc,
        country_event_provider: DisasterEventProvider | None = None,
        geographic_region_catalog: GeographicRegionCatalog | None = None,
        event_policies: EventPolicyRegistry | None = None,
    ) -> None:
        self._provider_registry = provider_registry
        self._clock = clock
        self._country_event_provider = country_event_provider
        self._country_catalog = country_catalog
        self._country_resolver = IncidentCountryResolver(
            country_catalog, geographic_region_catalog
        )
        self._event_policies = event_policies or default_event_policy_registry()

    async def country(
        self,
        watch: IncidentWatch,
        query: ActiveIncidentsQuery,
        *,
        now: datetime,
    ) -> IncidentRetrievalResult:
        if self._country_event_provider is None:
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
        physical_records = tuple(
            record
            for record in batch.records
            if record.observation_kind is not ObservationKind.ACQUISITION
        )
        observations = tuple(
            country_observation(record)
            for record in batch.records
            if record.observation_kind is ObservationKind.ACQUISITION
        )
        identities = policy.identify(physical_records).physical_events
        retained = tuple(
            sorted(
                (
                    country_incident(identity)
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
            observations=observations,
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
            time_window_days=(
                30
                if query.view
                in {
                    IncidentView.ONGOING,
                    IncidentView.RECENTLY_UPDATED,
                    IncidentView.HISTORICAL,
                }
                else query.time_window_days
            ),
            limit=query.acquisition_limit_per_disaster,
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

        admitted: list[ActiveIncident] = []
        observations: list[ActiveIncident] = []
        warnings: list[str] = []
        degraded = False
        retryable = False
        scan_complete = True
        records_seen = 0
        provider_attempts: list[ProviderAttempt] = []
        for registration in selection.registrations:
            (
                records,
                provider_observations,
                provider_warnings,
                provider_degraded,
                provider_retryable,
                provider_scan_complete,
                provider_records_seen,
                provider_attempt,
            ) = await self._query_provider(registration, provider_query, now=now)
            warnings.extend(provider_warnings)
            degraded = degraded or provider_degraded
            retryable = retryable or provider_retryable
            scan_complete = scan_complete and provider_scan_complete
            records_seen += provider_records_seen
            provider_attempts.append(provider_attempt)
            admitted.extend(records)
            observations.extend(provider_observations)

        resolved = resolve_worldwide_incidents(
            tuple(admitted),
            country_catalog=self._country_catalog,
            event_policies=self._event_policies,
        )
        sorted_incidents = tuple(
            sorted(
                resolved,
                key=lambda incident: (
                    -incident.event_time.timestamp(),
                    incident.event_id,
                    incident.source.source_id,
                ),
            )
        )
        retained = sorted_incidents
        state = (
            IncidentCoverageState.DEGRADED
            if degraded
            else IncidentCoverageState.EVENTS_FOUND
            if retained
            else IncidentCoverageState.NO_MATCHING_RECORDS
        )
        if query.view is IncidentView.ONGOING and not retained:
            warnings.append(
                "No source-backed ongoing lifecycle status was returned; an empty "
                "ongoing view does not establish that no event is active."
            )
        truncated = not scan_complete
        return IncidentRetrievalResult(
            incidents=retained,
            observations=tuple(
                sorted(
                    observations,
                    key=lambda incident: (
                        -incident.event_time.timestamp(),
                        incident.event_id,
                        incident.source.source_id,
                    ),
                )
            ),
            coverage=DisasterIncidentCoverage(
                disaster=disaster,
                state=state,
                incident_count=len(retained),
                providers=tuple(item.name for item in selection.registrations),
                detail=_coverage_detail(state, len(retained)),
                scan_complete=scan_complete,
                records_seen=records_seen,
                truncated=truncated,
            ),
            warnings=tuple(dict.fromkeys(warnings)),
            successful=bool(retained) or not degraded,
            retryable=retryable,
            provider_source_ids=tuple(
                item.source_id for item in selection.registrations if item.source_id
            ),
            provider_attempts=tuple(provider_attempts),
        )

    async def _query_provider(
        self,
        registration: ProviderRegistration,
        query: WorldwideDisasterQuery,
        *,
        now: datetime,
    ) -> tuple[
        tuple[ActiveIncident, ...],
        tuple[ActiveIncident, ...],
        tuple[str, ...],
        bool,
        bool,
        bool,
        int,
        ProviderAttempt,
    ]:
        provider = registration.worldwide_provider
        if (
            not registration.source_id
            or not registration.allowed_hosts
            or provider is None
        ):
            return (
                (),
                (),
                (
                    f"Worldwide provider {registration.name} has incomplete "
                    "executable authority.",
                ),
                True,
                False,
                False,
                0,
                ProviderAttempt(
                    source_id=registration.source_id or registration.name,
                    attempted_at=now,
                    outcome=ProviderAttemptOutcome.FAILED,
                    reason_code="configuration_rejected",
                ),
            )
        try:
            raw_batch = await provider.find_worldwide_events(query, now=now)
            batch = (
                raw_batch
                if isinstance(raw_batch, ProviderBatch)
                else ProviderBatch(tuple(raw_batch))
            )
        except Exception as error:
            failure = getattr(error, "failure", None)
            reason_code = str(getattr(failure, "reason_code", "invalid_payload"))
            retryable = bool(getattr(failure, "retryable", True))
            http_status = getattr(failure, "http_status", None)
            return (
                (),
                (),
                (
                    f"Worldwide provider {registration.name} could not be reached "
                    "or returned invalid data.",
                ),
                True,
                retryable,
                False,
                0,
                ProviderAttempt(
                    source_id=registration.source_id,
                    attempted_at=now,
                    outcome=ProviderAttemptOutcome.FAILED,
                    reason_code=reason_code,
                    retryable=retryable,
                    http_status=(
                        int(http_status) if isinstance(http_status, int) else None
                    ),
                ),
            )

        accepted: list[ActiveIncident] = []
        observations: list[ActiveIncident] = []
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
            normalized = incident(event, registration.tier, self._country_resolver)
            if event.observation_kind is ObservationKind.ACQUISITION:
                observations.append(normalized)
            else:
                accepted.append(normalized)
            if normalized.country is None:
                warnings.append(
                    "A worldwide event has no trusted country association and is "
                    "retained as a countryless incident."
                )
        for issue in batch.issues:
            if issue.reason_code == "empty_result":
                continue
            warnings.append(issue.message)
            degraded = True
            retryable = retryable or issue.retryable
        scan_complete = batch.scan_complete and not any(
            issue.reason_code == "pagination_limit_reached" for issue in batch.issues
        )
        material_issues = tuple(
            issue for issue in batch.issues if issue.reason_code != "empty_result"
        )
        attempt_outcome = (
            ProviderAttemptOutcome.EMPTY
            if not batch.records and not material_issues
            else ProviderAttemptOutcome.INCOMPLETE
            if not scan_complete or material_issues and batch.records
            else ProviderAttemptOutcome.FAILED
        )
        attempt_issue = material_issues[0] if material_issues else None
        provider_attempt = ProviderAttempt(
            source_id=registration.source_id,
            attempted_at=now,
            outcome=attempt_outcome,
            reason_code=(
                str(attempt_issue.reason_code) if attempt_issue is not None else None
            ),
            retryable=retryable,
            http_status=(
                attempt_issue.http_status if attempt_issue is not None else None
            ),
            records_seen=(
                batch.records_seen
                if batch.records_seen is not None
                else len(batch.records)
            ),
        )
        return (
            tuple(accepted),
            tuple(observations),
            tuple(dict.fromkeys(warnings)),
            degraded,
            retryable,
            scan_complete,
            (
                batch.records_seen
                if batch.records_seen is not None
                else len(batch.records)
            ),
            provider_attempt,
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
            "configured provider set after source-backed identity resolution."
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
