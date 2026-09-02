"""Serialization from application/domain results to HTTP response models."""

from disaster_monitor.domain.disaster import (
    IncidentWatch,
    IncidentWatchChange,
    WatchIncident,
)
from disaster_monitor.presentation.http.common_response_serialization import (
    _event_geometry_response,
    _source_response,
)
from disaster_monitor.presentation.http.schemas import (
    EventMeasurementResponse,
    IncidentWatchChangeResponse,
    IncidentWatchEventResponse,
    IncidentWatchResponse,
    IncidentWatchScopeResponse,
)


def _incident_watch_response(watch: IncidentWatch) -> IncidentWatchResponse:
    return IncidentWatchResponse(
        watch_id=watch.watch_id,
        disaster=watch.disaster,
        scope=IncidentWatchScopeResponse(
            kind=watch.scope.kind.value,
            country_code=watch.scope.country_code,
            country_name=watch.scope.country_name,
        ),
        enabled=watch.enabled,
        refresh_interval_seconds=watch.refresh_interval_seconds,
        created_at=watch.created_at,
        updated_at=watch.updated_at,
        next_refresh_at=watch.next_refresh_at,
        last_checked_at=watch.last_checked_at,
        coverage_state=(
            watch.coverage_state.value if watch.coverage_state is not None else None
        ),
        unread_change_count=watch.unread_change_count,
    )


def _incident_watch_event_response(
    incident: WatchIncident,
) -> IncidentWatchEventResponse:
    return IncidentWatchEventResponse(
        physical_event_id=incident.physical_event_id,
        event_id=incident.event_id,
        disaster=incident.disaster,
        location=incident.location,
        event_time=incident.event_time,
        geometry=_event_geometry_response(incident.geometry),
        measurements=[
            EventMeasurementResponse(
                kind=item.kind,
                value=item.value,
                unit=item.unit,
                source_id=item.source.source_id,
            )
            for item in incident.measurements
        ],
        provider_ids=list(incident.provider_ids),
        provider_tier=incident.provider_tier,
        source_authority=incident.source_authority,
        source=_source_response(incident.source),
        evidence_sources=[_source_response(item) for item in incident.evidence_sources],
    )


def _incident_watch_change_response(
    change: IncidentWatchChange,
) -> IncidentWatchChangeResponse:
    return IncidentWatchChangeResponse(
        change_id=change.change_id,
        watch_id=change.watch_id,
        kind=change.kind.value,
        summary=change.summary,
        detail=change.detail,
        created_at=change.created_at,
        read_at=change.read_at,
        source_ids=list(change.source_ids),
        observation_id=change.observation_id,
        previous_observation_id=change.previous_observation_id,
        before_hash=change.before_hash,
        after_hash=change.after_hash,
        incident=(
            _incident_watch_event_response(change.incident)
            if change.incident is not None
            else None
        ),
    )
