"""Bounded provider-backed discovery for the Active Incidents surface."""

import asyncio
import base64
import binascii
import hashlib
import json
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime, timedelta

from disaster_monitor.application.evidence.event_policies import (
    CompoundHazardCorrelationService,
)
from disaster_monitor.application.evidence.event_resolution import (
    EventPolicyRegistry,
)
from disaster_monitor.application.incidents.identity_assignments import (
    IncidentIdentityAssignments,
)
from disaster_monitor.application.incidents.meaningful_change import (
    mark_meaningful_changes,
)
from disaster_monitor.application.incidents.mention_geography import (
    resolve_event_places,
)
from disaster_monitor.application.incidents.models import (
    ActiveIncident,
    ActiveIncidentsQuery,
    ActiveIncidentsSnapshot,
    DisasterIncidentCoverage,
    IncidentCoverageState,
    IncidentView,
)
from disaster_monitor.application.incidents.news_projection import (
    coverage_with_news_candidates,
    merge_news_candidates,
)
from disaster_monitor.application.incidents.projection_codec import (
    projection_to_snapshot,
    snapshot_to_projection,
)
from disaster_monitor.application.incidents.retrieval import IncidentRetrieval
from disaster_monitor.application.incidents.snapshot_cache import (
    IncidentCursorExpiredError,
    IncidentSnapshotCache,
)
from disaster_monitor.application.incidents.watch_observation import observe_watch
from disaster_monitor.application.ports.disaster_information import (
    DisasterEventProvider,
)
from disaster_monitor.application.ports.discovery import DiscoveryStore
from disaster_monitor.application.ports.geographic_regions import (
    GeographicRegionCatalog,
)
from disaster_monitor.application.ports.geography import CountryCatalog
from disaster_monitor.application.ports.incident_identity_store import (
    IncidentIdentityStore,
)
from disaster_monitor.application.ports.incident_projection import (
    IncidentProjectionStore,
)
from disaster_monitor.application.ports.mention_geography import MentionPlaceResolver
from disaster_monitor.application.ports.news import NewsCandidateStore
from disaster_monitor.application.ports.provider_status import ProviderAttemptWriter
from disaster_monitor.application.sources.provider_registry import (
    ProviderRegistry,
)
from disaster_monitor.domain.disaster import (
    Disaster,
    IncidentWatch,
    IncidentWatchObservation,
)
from disaster_monitor.domain.disaster_types import (
    EventTimePrecision,
    event_temporality_overlaps,
)
from disaster_monitor.domain.event_identifiers import (
    EventIdentifierRole,
    event_identifier_role,
)
from disaster_monitor.domain.hazards.taxonomy import DEFAULT_HAZARD_TAXONOMY


def _now_utc() -> datetime:
    return datetime.now(UTC)


class ActiveIncidentsService:
    def __init__(
        self,
        provider_registry: ProviderRegistry,
        *,
        country_catalog: CountryCatalog,
        clock: Callable[[], datetime] = _now_utc,
        country_event_provider: DisasterEventProvider | None = None,
        geographic_region_catalog: GeographicRegionCatalog | None = None,
        event_policies: EventPolicyRegistry | None = None,
        correlation_service: CompoundHazardCorrelationService | None = None,
        projection_store: IncidentProjectionStore | None = None,
        read_from_projection: bool = False,
        provider_attempt_recorder: ProviderAttemptWriter | None = None,
        candidate_store: NewsCandidateStore | None = None,
        identity_store: IncidentIdentityStore | None = None,
        discovery_store: DiscoveryStore | None = None,
        discovery_place_resolver: MentionPlaceResolver | None = None,
    ) -> None:
        self._clock = clock
        self._discovery_store = discovery_store
        self._discovery_place_resolver = discovery_place_resolver
        self._retrieval = IncidentRetrieval(
            provider_registry,
            clock=clock,
            country_event_provider=country_event_provider,
            country_catalog=country_catalog,
            geographic_region_catalog=geographic_region_catalog,
            event_policies=event_policies,
        )
        self._correlation_service = (
            correlation_service or CompoundHazardCorrelationService()
        )
        self._projection_store = projection_store
        self._read_from_projection = read_from_projection
        self._provider_attempt_recorder = provider_attempt_recorder
        self._candidate_store = candidate_store
        self._snapshot_cache = IncidentSnapshotCache()
        self._acquisition_cache = IncidentSnapshotCache(
            maximum_bytes=32 * 1024**2, lifetime=timedelta(days=1)
        )
        self._acquisitions: OrderedDict[str, str] = OrderedDict()
        self._inflight: dict[str, asyncio.Task[ActiveIncidentsSnapshot]] = {}
        self._latest_snapshot: ActiveIncidentsSnapshot | None = None
        self._identities = (
            IncidentIdentityAssignments(identity_store) if identity_store else None
        )

    async def execute(
        self, query: ActiveIncidentsQuery | None = None
    ) -> ActiveIncidentsSnapshot:
        bounded_query = query or ActiveIncidentsQuery()
        if bounded_query.cursor is not None:
            return self._page_cached_snapshot(bounded_query)
        if self._projection_store is not None and self._read_from_projection:
            return await self._read_projection(bounded_query)
        key = _acquisition_key(bounded_query)
        version = self._acquisitions.get(key)
        cached = (
            self._acquisition_cache.get(version, now=self._clock()) if version else None
        )
        if cached is not None:
            if self._clock() - cached.retrieved_at >= timedelta(minutes=5):
                self._start_refresh(bounded_query)
                return replace(
                    _page_snapshot(cached, bounded_query),
                    is_stale=True,
                    refresh_state="refreshing",
                )
            return _page_snapshot(cached, bounded_query)
        return await self.refresh(bounded_query)

    async def refresh(
        self, query: ActiveIncidentsQuery | None = None
    ) -> ActiveIncidentsSnapshot:
        bounded_query = query or ActiveIncidentsQuery()
        full = await asyncio.shield(self._start_refresh(bounded_query))
        return _page_snapshot(full, bounded_query)

    def _start_refresh(
        self, query: ActiveIncidentsQuery
    ) -> asyncio.Task[ActiveIncidentsSnapshot]:
        key = _acquisition_key(query)
        running = self._inflight.get(key)
        if running is not None:
            return running
        acquisition_query = replace(
            query,
            country_code=None,
            search=None,
            page_size=None,
            cursor=None,
            hazard=query.hazard if _unsupported_hazard(query) else None,
        )

        async def acquire() -> ActiveIncidentsSnapshot:
            try:
                snapshot = await self._acquire(acquisition_query)
                if snapshot.snapshot_version:
                    self._acquisitions[key] = snapshot.snapshot_version
                    self._acquisitions.move_to_end(key)
                    while len(self._acquisitions) > 8:
                        self._acquisitions.popitem(last=False)
                if (
                    query.view is not IncidentView.HISTORICAL
                    and not _unsupported_hazard(query)
                ):
                    self._latest_snapshot = snapshot
                return snapshot
            finally:
                self._inflight.pop(key, None)

        task = asyncio.create_task(acquire())
        # Background refresh failures are observed; the previous snapshot stays usable.
        task.add_done_callback(
            lambda done: None if done.cancelled() else done.exception()
        )
        self._inflight[key] = task
        return task

    async def aclose(self) -> None:
        tasks = tuple(self._inflight.values())
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    async def lookup(self, identifier: str) -> ActiveIncident:
        if self._discovery_store is not None and identifier.startswith("discovery:"):
            from disaster_monitor.application.incidents.discovery_projection import (
                discovery_incident,
            )

            for run in await self._discovery_store.recent():
                for event in run.events:
                    if event.event_id == identifier:
                        if (
                            event.geometry is None
                            and event.event_time is not None
                            and self._discovery_place_resolver
                        ):
                            (event,) = await resolve_event_places(
                                (event,), self._discovery_place_resolver, maximum=2
                            )
                        return discovery_incident(
                            event, run.finished_at or run.interval.end
                        )
            raise LookupError("Discovered event is no longer retained. Run a new scan.")
        snapshot = await self.execute()
        matches = tuple(
            item
            for item in snapshot.incidents
            if identifier
            in {
                item.event_id,
                item.physical_event_id,
                *(
                    alias
                    for alias in item.provider_ids
                    if event_identifier_role(alias)
                    is EventIdentifierRole.PHYSICAL_EVENT
                ),
            }
        )
        if len(matches) > 1:
            raise ValueError(
                "The incident identifier is ambiguous: it matches multiple "
                "physical events."
            )
        if not matches:
            retained = (
                self._identities.lookup(identifier, now=self._clock())
                if self._identities
                else None
            )
            if retained:
                return retained
            raise LookupError(
                "Incident is unavailable in the retained source snapshots."
            )
        return matches[0]

    async def _acquire(self, query: ActiveIncidentsQuery) -> ActiveIncidentsSnapshot:
        """Acquire providers once, persist the complete result, and return a page."""
        bounded_query = query
        now = self._clock()
        previous_incidents = await self._previous_incidents()
        results = await asyncio.gather(
            *(
                self._retrieval.worldwide(disaster, bounded_query, now=now)
                for disaster in (
                    (bounded_query.hazard,)
                    if bounded_query.hazard is not None
                    and _unsupported_hazard(bounded_query)
                    else Disaster
                )
            )
        )
        prior_version = self._acquisitions.get(_acquisition_key(query))
        prior = (
            self._acquisition_cache.get(prior_version, now=now)
            if prior_version
            else None
        )
        failed_hazards = {
            result.coverage.disaster
            for result in results
            if not result.successful and not result.incidents
        }
        retained = (
            tuple(item for item in prior.incidents if item.disaster in failed_hazards)
            if prior
            else ()
        )
        if self._provider_attempt_recorder is not None:
            for result in results:
                for attempt in result.provider_attempts:
                    await self._provider_attempt_recorder.record_provider_attempt(
                        attempt
                    )
        provider_incidents = tuple(
            sorted(
                (
                    *retained,
                    *(incident for result in results for incident in result.incidents),
                ),
                key=lambda incident: (
                    -incident.event_time.timestamp(),
                    incident.disaster.value,
                    incident.event_id,
                    incident.source.source_id,
                ),
            )
        )
        candidates = (
            await self._candidate_store.latest_incident_candidates(
                since=(
                    bounded_query.occurrence_start
                    or now - timedelta(days=bounded_query.time_window_days)
                )
            )
            if self._candidate_store is not None
            else ()
        )
        incidents = mark_meaningful_changes(
            merge_news_candidates(
                provider_incidents,
                candidates,
                visible_at=now,
                previous_incidents=previous_incidents,
            ),
            previous_incidents,
            observed_at=now,
        )
        observations = tuple(
            sorted(
                (
                    observation
                    for result in results
                    for observation in result.observations
                ),
                key=lambda observation: (
                    -observation.event_time.timestamp(),
                    observation.disaster.value,
                    observation.event_id,
                    observation.source.source_id,
                ),
            )
        )
        full_snapshot = ActiveIncidentsSnapshot(
            retrieved_at=now,
            incidents=incidents,
            is_stale=bool(retained),
            refresh_state="stale" if retained else "fresh",
            coverage=coverage_with_news_candidates(
                tuple(
                    replace(
                        result.coverage,
                        incident_count=sum(
                            item.disaster is result.coverage.disaster
                            for item in incidents
                        ),
                        detail=result.coverage.detail
                        + (
                            " Retained the last successful incident rows; "
                            "source retrieval times are unchanged."
                            if result.coverage.disaster in failed_hazards
                            and any(
                                item.disaster is result.coverage.disaster
                                for item in retained
                            )
                            else ""
                        ),
                    )
                    for result in results
                ),
                candidates,
                incidents,
            ),
            warnings=tuple(
                dict.fromkeys(
                    (
                        *(warning for result in results for warning in result.warnings),
                        *(
                            (
                                "Provisional news-detected incidents are visible while "
                                "authoritative corroboration is pending.",
                            )
                            if candidates
                            else ()
                        ),
                    )
                )
            ),
            observations=observations,
            correlations=self._correlation_service.correlate(incidents),
            snapshot_version=_snapshot_version(now, incidents, observations),
            total_incident_count=len(incidents),
            historical_limitations=(
                (
                    "Historical results are bounded by each selected provider's "
                    "published retention, pagination, and availability; an empty "
                    "result is not proof that no event occurred.",
                )
                if bounded_query.occurrence_start is not None
                else ()
            ),
        )
        if self._identities is not None:
            full_snapshot = await self._identities.stabilize(full_snapshot)
        if self._projection_store is not None:
            await self._projection_store.append_incident_projection(
                snapshot_to_projection(full_snapshot, created_at=now)
            )
        self._remember_snapshot(full_snapshot)
        return _page_snapshot(full_snapshot, bounded_query)

    async def _read_projection(
        self, query: ActiveIncidentsQuery
    ) -> ActiveIncidentsSnapshot:
        projection = await self._projection_store.latest_incident_projection()  # type: ignore[union-attr]
        if projection is None:
            return _empty_projection_snapshot(
                self._clock(),
                "No durable worldwide incident projection is available yet; "
                "the scheduler has not completed an initial refresh.",
            )
        try:
            snapshot = projection_to_snapshot(projection)
        except ValueError:
            return _empty_projection_snapshot(
                projection.retrieved_at,
                "The latest durable worldwide incident projection is invalid; "
                "operator review is required before it can be served.",
            )
        self._remember_snapshot(snapshot)
        return _page_snapshot(snapshot, query)

    async def _previous_incidents(self) -> tuple[ActiveIncident, ...]:
        if self._projection_store is None:
            return self._latest_snapshot.incidents if self._latest_snapshot else ()
        projection = await self._projection_store.latest_incident_projection()
        if projection is None:
            return ()
        try:
            return projection_to_snapshot(projection).incidents
        except ValueError:
            return ()

    async def observe_watch(self, watch: IncidentWatch) -> IncidentWatchObservation:
        return await observe_watch(self._retrieval, watch, now=self._clock())

    def _remember_snapshot(self, snapshot: ActiveIncidentsSnapshot) -> None:
        version = snapshot.snapshot_version
        if version is None:
            return
        self._snapshot_cache.put(snapshot, now=self._clock())
        self._acquisition_cache.put(snapshot, now=self._clock())

    def _page_cached_snapshot(
        self, query: ActiveIncidentsQuery
    ) -> ActiveIncidentsSnapshot:
        token = _decode_cursor(query.cursor or "")
        snapshot_version = token["snapshot_version"]
        offset = token["offset"]
        if not isinstance(snapshot_version, str) or not isinstance(offset, int):
            raise ValueError("The incident cursor is invalid.")
        snapshot = self._snapshot_cache.get(snapshot_version, now=self._clock())
        if snapshot is None:
            raise IncidentCursorExpiredError(
                "The incident snapshot cursor has expired. Refresh the list "
                "to continue."
            )
        if token["query"] != _cursor_query_key(query):
            raise ValueError("The incident cursor does not match the query.")
        return _page_snapshot(snapshot, query, offset=offset)


def _snapshot_version(
    retrieved_at: datetime,
    incidents: tuple[ActiveIncident, ...],
    observations: tuple[ActiveIncident, ...],
) -> str:
    material = "|".join(
        (
            retrieved_at.isoformat(),
            *(
                f"incident:{item.disaster.value}:{item.event_id}:{item.source.source_id}"
                for item in incidents
            ),
            *(
                f"observation:{item.disaster.value}:{item.event_id}:{item.source.source_id}"
                for item in observations
            ),
        )
    )
    return f"incident-snapshot:{hashlib.sha256(material.encode()).hexdigest()[:24]}"


def _cursor_query_key(query: ActiveIncidentsQuery) -> str:
    return json.dumps(
        {
            "time_window_days": query.time_window_days,
            "limit_per_disaster": query.limit_per_disaster,
            "acquisition_limit_per_disaster": query.acquisition_limit_per_disaster,
            "view": query.view.value,
            "hazard": query.hazard.value if query.hazard is not None else None,
            "country_code": query.country_code,
            "search": query.search,
            "page_size": query.page_size,
            "occurrence_start": (
                query.occurrence_start.isoformat()
                if query.occurrence_start is not None
                else None
            ),
            "occurrence_end": (
                query.occurrence_end.isoformat()
                if query.occurrence_end is not None
                else None
            ),
        },
        sort_keys=True,
        separators=(",", ":"),
    )


def _encode_cursor(
    snapshot_version: str, offset: int, query: ActiveIncidentsQuery
) -> str:
    payload = json.dumps(
        {
            "snapshot_version": snapshot_version,
            "offset": offset,
            "query": _cursor_query_key(query),
        },
        separators=(",", ":"),
    ).encode()
    return base64.urlsafe_b64encode(payload).decode().rstrip("=")


def _decode_cursor(value: str) -> dict[str, object]:
    try:
        padded = value + "=" * (-len(value) % 4)
        decoded = json.loads(base64.urlsafe_b64decode(padded).decode())
        if (
            not isinstance(decoded, dict)
            or not isinstance(decoded.get("snapshot_version"), str)
            or not isinstance(decoded.get("query"), str)
            or not isinstance(decoded.get("offset"), int)
            or decoded["offset"] < 0
        ):
            raise ValueError
        return decoded
    except (
        ValueError,
        TypeError,
        UnicodeDecodeError,
        json.JSONDecodeError,
        binascii.Error,
    ) as error:
        raise ValueError("The incident cursor is invalid.") from error


def _page_snapshot(
    snapshot: ActiveIncidentsSnapshot,
    query: ActiveIncidentsQuery,
    *,
    offset: int = 0,
) -> ActiveIncidentsSnapshot:
    filtered = tuple(
        incident
        for incident in snapshot.incidents
        if _matches_query(incident, query, reference=snapshot.retrieved_at)
    )
    if query.view is IncidentView.RECENTLY_UPDATED:
        filtered = tuple(
            sorted(
                filtered,
                key=lambda item: (
                    -(item.last_meaningful_change_at or item.event_time).timestamp(),
                    item.event_id,
                ),
            )
        )
    page_size = query.page_size
    if page_size is None:
        page = filtered[offset:]
        next_cursor = None
        has_more = False
    else:
        page = filtered[offset : offset + page_size]
        next_offset = offset + len(page)
        has_more = next_offset < len(filtered)
        next_cursor = (
            _encode_cursor(snapshot.snapshot_version or "", next_offset, query)
            if has_more
            else None
        )
    previously_visible_ids = {item.event_id for item in filtered[:offset]}
    visible_ids = previously_visible_ids | {item.event_id for item in page}
    observations = tuple(
        observation
        for observation in snapshot.observations
        if _matches_query(observation, query, reference=snapshot.retrieved_at)
    )
    return ActiveIncidentsSnapshot(
        retrieved_at=snapshot.retrieved_at,
        incidents=page,
        coverage=snapshot.coverage,
        warnings=snapshot.warnings,
        observations=observations,
        correlations=tuple(
            correlation
            for correlation in snapshot.correlations
            if (endpoints := {correlation.first_event_id, correlation.second_event_id})
            <= visible_ids
            and not endpoints <= previously_visible_ids
        ),
        snapshot_version=snapshot.snapshot_version,
        next_cursor=next_cursor,
        has_more=has_more,
        total_incident_count=len(filtered),
        historical_limitations=snapshot.historical_limitations,
        refresh_state=snapshot.refresh_state,
        is_stale=snapshot.is_stale,
    )


def _empty_projection_snapshot(
    retrieved_at: datetime, warning: str
) -> ActiveIncidentsSnapshot:
    return ActiveIncidentsSnapshot(
        retrieved_at=retrieved_at,
        incidents=(),
        observations=(),
        coverage=tuple(
            DisasterIncidentCoverage(
                disaster=disaster,
                state=IncidentCoverageState.UNAVAILABLE,
                incident_count=0,
                providers=(),
                detail="No durable worldwide projection is available.",
            )
            for disaster in Disaster
        ),
        warnings=(warning,),
        correlations=(),
        snapshot_version=None,
        total_incident_count=0,
    )


def _acquisition_key(query: ActiveIncidentsQuery) -> str:
    return json.dumps(
        {
            "days": query.time_window_days if query.view is IncidentView.RECENT else 30,
            "limit": query.acquisition_limit_per_disaster,
            "historical": query.view is IncidentView.HISTORICAL,
            "start": query.occurrence_start.isoformat()
            if query.occurrence_start
            else None,
            "end": query.occurrence_end.isoformat() if query.occurrence_end else None,
            "unsupported_hazard": query.hazard.value
            if query.hazard is not None and _unsupported_hazard(query)
            else None,
        },
        sort_keys=True,
    )


def _matches_query(
    incident: ActiveIncident,
    query: ActiveIncidentsQuery,
    *,
    reference: datetime,
) -> bool:
    if query.hazard is not None and incident.disaster is not query.hazard:
        return False
    if query.country_code is not None and (
        incident.country is None or incident.country.country_code != query.country_code
    ):
        return False
    if query.search is not None:
        country_values = (
            (incident.country.country_code, incident.country.country_name)
            if incident.country is not None
            else ()
        )
        haystack = " ".join(
            (
                incident.event_id,
                incident.location,
                incident.source.source_id,
                incident.source.publisher,
                incident.source.title,
                *country_values,
            )
        ).casefold()
        if query.search.casefold() not in haystack:
            return False
    start = reference - timedelta(days=query.time_window_days)
    if query.view is IncidentView.ONGOING:
        return incident.activity_status.value == "ongoing"
    if query.view is IncidentView.RECENTLY_UPDATED:
        effective = incident.last_meaningful_change_at or incident.event_time
        return start <= effective <= reference
    if query.view is IncidentView.HISTORICAL:
        historical_start = query.occurrence_start or start
        historical_end = query.occurrence_end or reference
        return event_temporality_overlaps(
            incident.event_time,
            incident.event_time_end,
            incident.event_time_precision,
            historical_start,
            historical_end,
        )
    if incident.event_time_precision is EventTimePrecision.EXACT:
        return start <= incident.event_time <= reference
    return event_temporality_overlaps(
        incident.event_time,
        incident.event_time_end,
        incident.event_time_precision,
        start,
        reference,
    )


__all__ = [
    "ActiveIncidentsQuery",
    "IncidentView",
    "IncidentCoverageState",
    "ActiveIncident",
    "DisasterIncidentCoverage",
    "ActiveIncidentsSnapshot",
    "ActiveIncidentsService",
]


def _unsupported_hazard(query: ActiveIncidentsQuery) -> bool:
    return (
        query.hazard is not None
        and not DEFAULT_HAZARD_TAXONOMY.require(
            query.hazard.value
        ).incident_discovery_supported
    )
