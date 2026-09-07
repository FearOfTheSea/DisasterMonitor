"""Bounded provider-backed discovery for the Active Incidents surface."""

import asyncio
from collections.abc import Callable
from datetime import UTC, datetime

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
)
from disaster_monitor.application.incidents.retrieval import IncidentRetrieval
from disaster_monitor.application.incidents.watch_observation import observe_watch
from disaster_monitor.application.ports.disaster_information import (
    DisasterEventProvider,
)
from disaster_monitor.application.ports.geography import CountryCatalog
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
        clock: Callable[[], datetime] = _now_utc,
        country_event_provider: DisasterEventProvider | None = None,
        country_catalog: CountryCatalog | None = None,
        event_policies: EventPolicyRegistry | None = None,
        correlation_service: CompoundHazardCorrelationService | None = None,
    ) -> None:
        self._clock = clock
        self._retrieval = IncidentRetrieval(
            provider_registry,
            clock=clock,
            country_event_provider=country_event_provider,
            country_catalog=country_catalog,
            event_policies=event_policies,
        )
        self._correlation_service = (
            correlation_service or CompoundHazardCorrelationService()
        )

    async def execute(
        self, query: ActiveIncidentsQuery | None = None
    ) -> ActiveIncidentsSnapshot:
        bounded_query = query or ActiveIncidentsQuery()
        now = self._clock()
        results = await asyncio.gather(
            *(
                self._retrieval.worldwide(disaster, bounded_query, now=now)
                for disaster in Disaster
            )
        )
        incidents = tuple(
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
        return ActiveIncidentsSnapshot(
            retrieved_at=now,
            incidents=incidents,
            coverage=tuple(result.coverage for result in results),
            warnings=tuple(
                dict.fromkeys(
                    warning for result in results for warning in result.warnings
                )
            ),
            correlations=self._correlation_service.correlate(incidents),
        )

    async def observe_watch(self, watch: IncidentWatch) -> IncidentWatchObservation:
        return await observe_watch(self._retrieval, watch, now=self._clock())


__all__ = [
    "ActiveIncidentsQuery",
    "IncidentCoverageState",
    "ActiveIncident",
    "DisasterIncidentCoverage",
    "ActiveIncidentsSnapshot",
    "ActiveIncidentsService",
]
