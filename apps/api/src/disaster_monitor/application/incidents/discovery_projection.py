"""Adapt retained discovery events to the existing incident inspection contract."""

from datetime import datetime

from disaster_monitor.application.incidents.models import ActiveIncident
from disaster_monitor.domain.disaster_types import EventTimePrecision, ProviderTier
from disaster_monitor.domain.discovery import DiscoveryEvent
from disaster_monitor.domain.news import IncidentCandidateStatus


def discovery_incident(
    event: DiscoveryEvent, retrieved_at: datetime, *, scan_id: str
) -> ActiveIncident:
    sources = (
        *tuple(report.article.source for report in event.reports),
        *event.supplemental_sources,
    )
    onset = next(
        (
            report.mention.time
            for report in event.reports
            if event.event_time is not None
            and report.mention
            and report.mention.time
            and report.mention.time.start == event.event_time
        ),
        None,
    )
    return ActiveIncident(
        # Extraction identifiers are local to a retained assessment. This reference
        # selects its evidence version; it is not a global physical-event identity.
        event_id=f"discovery:{scan_id}:{event.event_id}",
        disaster=event.disaster,
        country=None,
        location=event.location,
        # Existing incident transport requires a sort/display clock. Its basis is
        # explicit; unknown onset must never be used for evidence or imagery targeting.
        event_time=event.event_time or sources[0].published_at or retrieved_at,
        geometry=event.geometry,
        event_time_precision=EventTimePrecision.DAY
        if onset and onset.precision in ("day", "range")
        else EventTimePrecision.EXACT,
        measurements=(),
        provider_ids=(),
        provider_tier=ProviderTier.SECONDARY,
        source_authority=sources[0].authority,
        source=sources[0],
        evidence_sources=sources,
        verification_status=IncidentCandidateStatus.PROVISIONAL_NEWS_DETECTED,
        discovery_event=event,
    )
