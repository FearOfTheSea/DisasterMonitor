"""Project and reconcile eligible news candidates into incident snapshots."""

from dataclasses import replace
from datetime import datetime

from disaster_monitor.application.incidents.models import (
    ActiveIncident,
    DisasterIncidentCoverage,
    IncidentCoverageState,
)
from disaster_monitor.domain.disaster import Disaster, ProviderTier
from disaster_monitor.domain.news import (
    IncidentCandidate,
    IncidentCandidateStatus,
    IncidentDetectionTimeline,
)


def merge_news_candidates(
    incidents: tuple[ActiveIncident, ...],
    candidates: tuple[IncidentCandidate, ...],
    *,
    visible_at: datetime,
    previous_incidents: tuple[ActiveIncident, ...] = (),
) -> tuple[ActiveIncident, ...]:
    merged = list(incidents)
    previous_by_id = {item.event_id: item for item in previous_incidents}
    for candidate in candidates:
        if candidate.status is IncidentCandidateStatus.REJECTED:
            continue
        match_index = next(
            (
                index
                for index, incident in enumerate(merged)
                if _candidate_matches_incident(candidate, incident)
            ),
            None,
        )
        previous = previous_by_id.get(candidate.candidate_id)
        if previous is None and match_index is not None:
            previous = next(
                (
                    incident
                    for incident in previous_incidents
                    if _candidate_matches_incident(candidate, incident)
                ),
                None,
            )
        timeline = IncidentDetectionTimeline(
            news_break_at=candidate.news_break_at,
            first_observed_at=candidate.first_observed_at,
            candidate_created_at=candidate.candidate_created_at,
            verified_at=(
                (previous.detection.verified_at if previous is not None else None)
                or visible_at
                if match_index is not None
                else candidate.verified_at
            ),
            monitor_visible_at=(
                previous.detection.monitor_visible_at if previous is not None else None
            )
            or visible_at,
            assistant_ready_at=(
                previous.detection.assistant_ready_at if previous is not None else None
            )
            or visible_at,
        )
        if match_index is not None:
            incident = merged[match_index]
            evidence = {item.source_id: item for item in incident.evidence_sources}
            evidence.update({item.source_id: item for item in candidate.sources})
            merged[match_index] = replace(
                incident,
                evidence_sources=tuple(
                    sorted(evidence.values(), key=lambda item: item.source_id)
                ),
                verification_status=IncidentCandidateStatus.SOURCE_BACKED,
                detection=timeline,
            )
            continue
        source = candidate.sources[0]
        merged.append(
            ActiveIncident(
                event_id=candidate.candidate_id,
                disaster=candidate.disaster,
                country=None,
                location=candidate.location,
                event_time=candidate.event_time,
                geometry=None,
                measurements=(),
                provider_ids=tuple(item.source_id for item in candidate.sources),
                provider_tier=ProviderTier.SECONDARY,
                source_authority=source.authority,
                source=source,
                evidence_sources=candidate.sources,
                verification_status=candidate.status,
                detection=timeline,
            )
        )
    return tuple(
        sorted(
            merged,
            key=lambda item: (
                -item.event_time.timestamp(),
                item.disaster.value,
                item.event_id,
            ),
        )
    )


def coverage_with_news_candidates(
    coverage: tuple[DisasterIncidentCoverage, ...],
    candidates: tuple[IncidentCandidate, ...],
    projected_incidents: tuple[ActiveIncident, ...],
) -> tuple[DisasterIncidentCoverage, ...]:
    projected_ids = {incident.event_id for incident in projected_incidents}
    counts = {
        disaster: sum(
            candidate.disaster is disaster
            and candidate.status is not IncidentCandidateStatus.REJECTED
            and candidate.candidate_id in projected_ids
            for candidate in candidates
        )
        for disaster in Disaster
    }
    return tuple(
        replace(
            item,
            state=(
                IncidentCoverageState.EVENTS_FOUND
                if counts[item.disaster]
                else item.state
            ),
            incident_count=item.incident_count + counts[item.disaster],
            providers=(
                tuple(dict.fromkeys((*item.providers, "Major-news sensing")))
                if counts[item.disaster]
                else item.providers
            ),
            detail=(
                "Includes source-attributed provisional news candidates; "
                "authoritative corroboration may be pending."
                if counts[item.disaster]
                else item.detail
            ),
        )
        for item in coverage
    )


def _candidate_matches_incident(
    candidate: IncidentCandidate, incident: ActiveIncident
) -> bool:
    if candidate.disaster is not incident.disaster:
        return False
    if abs((candidate.event_time - incident.event_time).total_seconds()) > 72 * 3600:
        return False
    return (
        len(_identity_tokens(candidate.location) & _identity_tokens(incident.location))
        >= 2
    )


def _identity_tokens(value: str) -> set[str]:
    return {
        token for token in value.casefold().replace(",", " ").split() if len(token) >= 4
    }
