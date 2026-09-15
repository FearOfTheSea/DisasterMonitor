"""Deterministic evidence-change tracking for incident recency."""

from dataclasses import replace
from datetime import datetime

from disaster_monitor.application.incidents.models import ActiveIncident


def mark_meaningful_changes(
    incidents: tuple[ActiveIncident, ...],
    previous: tuple[ActiveIncident, ...],
    *,
    observed_at: datetime,
) -> tuple[ActiveIncident, ...]:
    """Carry forward recency unless source-backed incident content changed."""
    previous_by_identity = {_identity(item): item for item in previous}
    marked: list[ActiveIncident] = []
    for incident in incidents:
        prior = previous_by_identity.get(_identity(incident))
        changed_at = observed_at
        if prior is not None and _evidence_signature(prior) == _evidence_signature(
            incident
        ):
            changed_at = prior.last_meaningful_change_at or prior.event_time
        marked.append(replace(incident, last_meaningful_change_at=changed_at))
    return tuple(marked)


def _identity(incident: ActiveIncident) -> tuple[str, str]:
    stable_id = incident.physical_event_id or (
        f"{incident.source.source_id}:{incident.event_id}"
    )
    return incident.disaster.value, stable_id.casefold()


def _evidence_signature(incident: ActiveIncident) -> tuple[object, ...]:
    geometry = incident.geometry
    return (
        incident.disaster.value,
        incident.event_time,
        incident.location,
        incident.country,
        (
            None
            if geometry is None
            else (
                geometry.kind.value,
                geometry.coordinates,
                geometry.source.source_id,
            )
        ),
        tuple(
            (item.kind.value, item.value, item.unit, item.source.source_id)
            for item in incident.measurements
        ),
        incident.provider_ids,
        incident.lineage_ids,
        incident.activity_status.value,
        incident.verification_status.value,
        tuple(item.source_id for item in incident.evidence_sources),
    )


__all__ = ["mark_meaningful_changes"]
