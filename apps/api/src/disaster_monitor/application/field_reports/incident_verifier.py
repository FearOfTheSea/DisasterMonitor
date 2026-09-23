"""Resolve field-report event references from the durable incident projection."""

from disaster_monitor.application.field_reports.service import (
    IncidentEvidenceUnavailableError,
)
from disaster_monitor.application.incidents.projection_codec import (
    projection_to_snapshot,
)
from disaster_monitor.application.ports.incident_projection import (
    IncidentProjectionStore,
)
from disaster_monitor.domain.news import IncidentCandidateStatus


class ProjectionIncidentVerifier:
    def __init__(self, projection_store: IncidentProjectionStore) -> None:
        self._projection_store = projection_store

    async def exists(self, event_id: str) -> bool:
        projection = await self._projection_store.latest_incident_projection()
        if projection is None:
            raise IncidentEvidenceUnavailableError(
                "Current incident evidence is unavailable."
            )
        try:
            snapshot = projection_to_snapshot(projection)
        except ValueError as error:
            raise IncidentEvidenceUnavailableError(
                "Current incident evidence is invalid."
            ) from error
        return any(
            incident.event_id == event_id
            and incident.verification_status is IncidentCandidateStatus.SOURCE_BACKED
            for incident in snapshot.incidents
        )
