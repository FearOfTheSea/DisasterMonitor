"""Shared serialization for list, lookup, and standalone incident evidence."""

from disaster_monitor.application.incidents.models import ActiveIncident
from disaster_monitor.presentation.http.common_response_serialization import (
    _event_geometry_response,
    _source_response,
)
from disaster_monitor.presentation.http.schemas import (
    ActiveIncidentCountryResponse,
    ActiveIncidentResponse,
    EventMeasurementResponse,
    IncidentDetectionTimelineResponse,
)


def active_incident_response(incident: ActiveIncident) -> ActiveIncidentResponse:
    country = incident.country
    return ActiveIncidentResponse(
        event_id=incident.event_id,
        physical_event_id=incident.physical_event_id,
        disaster=incident.disaster,
        country=(
            None
            if country is None
            else ActiveIncidentCountryResponse(
                code=country.country_code,
                name=country.country_name,
                association_basis=country.basis.value,
                distance_km=country.distance_km,
            )
        ),
        location=incident.location,
        event_time=incident.event_time,
        event_time_end=incident.event_time_end,
        event_time_precision=incident.event_time_precision,
        geometry=_event_geometry_response(incident.geometry),
        measurements=[
            EventMeasurementResponse(
                kind=measurement.kind,
                value=measurement.value,
                unit=measurement.unit,
                source_id=measurement.source.source_id,
            )
            for measurement in incident.measurements
        ],
        provider_ids=list(incident.provider_ids),
        lineage_ids=list(incident.lineage_ids),
        provider_tier=incident.provider_tier,
        source_authority=incident.source_authority,
        source=_source_response(incident.source),
        evidence_sources=[
            _source_response(source) for source in incident.evidence_sources
        ],
        observation_kind=incident.observation_kind.value,
        activity_status=incident.activity_status,
        verification_status=incident.verification_status.value,
        detection=IncidentDetectionTimelineResponse(
            news_break_at=incident.detection.news_break_at,
            first_observed_at=incident.detection.first_observed_at,
            candidate_created_at=incident.detection.candidate_created_at,
            verified_at=incident.detection.verified_at,
            monitor_visible_at=incident.detection.monitor_visible_at,
            assistant_ready_at=incident.detection.assistant_ready_at,
        ),
        last_meaningful_change_at=incident.last_meaningful_change_at,
    )
