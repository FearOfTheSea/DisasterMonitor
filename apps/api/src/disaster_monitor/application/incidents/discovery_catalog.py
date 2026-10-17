"""Keep existing disaster catalogs as supplemental, independently acquired evidence."""

from collections.abc import AsyncIterator

from disaster_monitor.application.incidents.active_incidents import (
    ActiveIncidentsService,
)
from disaster_monitor.application.incidents.models import ActiveIncidentsQuery
from disaster_monitor.domain.discovery import (
    DiscoveryArticle,
    DiscoveryBatch,
    ReportingInterval,
)


class SupplementalIncidentCatalog:
    source_id = "provider-catalogs"

    def __init__(self, incidents: ActiveIncidentsService) -> None:
        self._incidents = incidents

    async def discover(
        self, *, interval: ReportingInterval
    ) -> AsyncIterator[DiscoveryBatch]:
        snapshot = await self._incidents.execute(
            ActiveIncidentsQuery(time_window_days=interval.days)
        )
        yield DiscoveryBatch(
            supplemental=tuple(
                DiscoveryArticle(
                    source=item.source,
                    text="",
                    location=item.location,
                    event_time=item.event_time,
                    geometry=item.geometry,
                    event_key=item.event_id,
                )
                for item in snapshot.incidents
            ),
            issues=tuple(
                f"Supplemental catalog: {warning}" for warning in snapshot.warnings
            ),
        )
