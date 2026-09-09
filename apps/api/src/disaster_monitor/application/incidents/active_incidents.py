"""Bounded provider-backed discovery for the Active Incidents surface."""

import asyncio
import base64
import binascii
import hashlib
import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from disaster_monitor.application.evidence.event_policies import (
    CompoundHazardCorrelationService,
)
from disaster_monitor.application.evidence.event_resolution import (
    EventPolicyRegistry,
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
from disaster_monitor.application.incidents.watch_observation import observe_watch
from disaster_monitor.application.ports.disaster_information import (
    DisasterEventProvider,
)
from disaster_monitor.application.ports.geographic_regions import (
    GeographicRegionCatalog,
)
from disaster_monitor.application.ports.geography import CountryCatalog
from disaster_monitor.application.ports.incident_projection import (
    IncidentProjectionStore,
)
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
    ) -> None:
        self._clock = clock
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
        self._snapshot_cache: dict[str, ActiveIncidentsSnapshot] = {}

    async def execute(
        self, query: ActiveIncidentsQuery | None = None
    ) -> ActiveIncidentsSnapshot:
        bounded_query = query or ActiveIncidentsQuery()
        if bounded_query.cursor is not None:
            return self._page_cached_snapshot(bounded_query)
        if self._projection_store is not None and self._read_from_projection:
            return await self._read_projection(bounded_query)
        return await self.refresh(bounded_query)

    async def refresh(
        self, query: ActiveIncidentsQuery | None = None
    ) -> ActiveIncidentsSnapshot:
        """Acquire providers once, persist the complete result, and return a page."""
        bounded_query = query or ActiveIncidentsQuery()
        now = self._clock()
        previous_incidents = await self._previous_incidents()
        results = await asyncio.gather(
            *(
                self._retrieval.worldwide(disaster, bounded_query, now=now)
                for disaster in Disaster
            )
        )
        if self._provider_attempt_recorder is not None:
            for result in results:
                for attempt in result.provider_attempts:
                    await self._provider_attempt_recorder.record_provider_attempt(
                        attempt
                    )
        provider_incidents = tuple(
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
        candidates = (
            await self._candidate_store.latest_incident_candidates(
                since=now - timedelta(days=bounded_query.time_window_days)
            )
            if self._candidate_store is not None
            else ()
        )
        incidents = merge_news_candidates(
            provider_incidents,
            candidates,
            visible_at=now,
            previous_incidents=previous_incidents,
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
            coverage=coverage_with_news_candidates(
                tuple(result.coverage for result in results), candidates, incidents
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
        )
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
            return ()
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
        self._snapshot_cache[version] = snapshot
        if len(self._snapshot_cache) > 8:
            oldest = next(iter(self._snapshot_cache))
            del self._snapshot_cache[oldest]

    def _page_cached_snapshot(
        self, query: ActiveIncidentsQuery
    ) -> ActiveIncidentsSnapshot:
        token = _decode_cursor(query.cursor or "")
        snapshot_version = token["snapshot_version"]
        offset = token["offset"]
        if not isinstance(snapshot_version, str) or not isinstance(offset, int):
            raise ValueError("The incident cursor is invalid.")
        snapshot = self._snapshot_cache.get(snapshot_version)
        if snapshot is None:
            raise ValueError("The incident snapshot cursor has expired.")
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
            if {correlation.first_event_id, correlation.second_event_id}
            <= {item.event_id for item in page}
        ),
        snapshot_version=snapshot.snapshot_version,
        next_cursor=next_cursor,
        has_more=has_more,
        total_incident_count=len(filtered),
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
        effective = (
            incident.source.updated_at
            or incident.source.published_at
            or incident.event_time
        )
        return start <= effective <= reference
    if query.view is IncidentView.HISTORICAL:
        return start <= incident.event_time <= reference
    return start <= incident.event_time <= reference


__all__ = [
    "ActiveIncidentsQuery",
    "IncidentView",
    "IncidentCoverageState",
    "ActiveIncident",
    "DisasterIncidentCoverage",
    "ActiveIncidentsSnapshot",
    "ActiveIncidentsService",
]
