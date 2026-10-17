"""Adapt retained discovery events to the existing incident inspection contract."""

from datetime import datetime

from disaster_monitor.application.incidents.models import ActiveIncident
from disaster_monitor.domain.disaster_types import ProviderTier
from disaster_monitor.domain.discovery import DiscoveryEvent
from disaster_monitor.domain.news import IncidentCandidateStatus


def discovery_incident(event: DiscoveryEvent, retrieved_at: datetime) -> ActiveIncident:
    sources = (
        *tuple(report.article.source for report in event.reports),
        *event.supplemental_sources,
    )
    return ActiveIncident(
        event_id=event.event_id,
        disaster=event.disaster,
        country=None,
        location=event.location,
        # Existing incident transport requires a sort/display clock. Its basis is
        # explicit; unknown onset must never be used for evidence or imagery targeting.
        event_time=event.event_time or sources[0].published_at or retrieved_at,
        geometry=event.geometry,
        measurements=(),
        provider_ids=(),
        provider_tier=ProviderTier.SECONDARY,
        source_authority=sources[0].authority,
        source=sources[0],
        evidence_sources=sources,
        verification_status=IncidentCandidateStatus.PROVISIONAL_NEWS_DETECTED,
        discovery_event=event,
    )
