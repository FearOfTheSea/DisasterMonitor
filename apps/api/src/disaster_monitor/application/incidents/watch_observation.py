"""Bounded provider-backed discovery for the Active Incidents surface."""

from datetime import datetime

from disaster_monitor.application.evidence.evidence_state import source_is_stale
from disaster_monitor.application.incidents.models import (
    ActiveIncident,
    ActiveIncidentsQuery,
)
from disaster_monitor.application.incidents.retrieval import IncidentRetrieval
from disaster_monitor.domain.disaster import (
    IncidentWatch,
    IncidentWatchObservation,
    WatchCoverageState,
    WatchIncident,
    WatchScopeKind,
)


async def observe_watch(
    retrieval: IncidentRetrieval, watch: IncidentWatch, *, now: datetime
) -> IncidentWatchObservation:
    """Observe one watch through the same bounded registered-provider path."""
    query = ActiveIncidentsQuery()
    result = (
        await retrieval.worldwide(watch.disaster, query, now=now)
        if watch.scope.kind is WatchScopeKind.WORLDWIDE
        else await retrieval.country(watch, query, now=now)
    )
    coverage = WatchCoverageState(result.coverage.state.value)
    if (
        coverage is WatchCoverageState.EVENTS_FOUND
        and result.incidents
        and any(
            source_is_stale(item.source.effective_at, now) for item in result.incidents
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
