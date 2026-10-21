"""Shared serialization for list, lookup, and standalone incident evidence."""

from disaster_monitor.application.incidents.models import ActiveIncident
from disaster_monitor.domain.discovery import fatality_accounts
from disaster_monitor.domain.discovery_claim_scope import scoped_disaster_text
from disaster_monitor.domain.event_mentions import HazardEpisodeAccount
from disaster_monitor.domain.reported_impacts import (
    ReportedImpact,
    extract_reported_impacts,
)
from disaster_monitor.presentation.http.common_response_serialization import (
    _event_geometry_response,
    _source_response,
)
from disaster_monitor.presentation.http.event_schemas import (
    DiscoveryReportResponse,
    HazardEpisodeAccountResponse,
    ReportedImpactResponse,
)
from disaster_monitor.presentation.http.schemas import (
    ActiveIncidentCountryResponse,
    ActiveIncidentResponse,
    EventMeasurementResponse,
    IncidentDetectionTimelineResponse,
)


def _impact_response(claim: ReportedImpact) -> ReportedImpactResponse:
    return ReportedImpactResponse.model_validate(
        {
            "category": claim.fact.category,
            "label": claim.fact.label,
            "value": claim.fact.value,
            "excerpt": claim.excerpt,
            "qualifiers": list(claim.qualifiers),
        }
    )


def _episode_response(
    account: HazardEpisodeAccount | None,
) -> HazardEpisodeAccountResponse | None:
    if account is None:
        return None
    return HazardEpisodeAccountResponse(
        account_id=account.account_id,
        hazards=list(account.hazards),
        location=account.place.wording,
        event_date_wording=account.time.wording,
        event_time=account.time.start,
        excerpt=account.excerpt,
        claims=[_impact_response(claim) for claim in account.claims],
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
        event_time=incident.discovery_event.event_time
        if incident.discovery_event
        else incident.event_time,
        event_time_basis="unknown"
        if incident.discovery_event and incident.discovery_event.event_time is None
        else "reported",
        independent_origins=incident.discovery_event.independent_origins
        if incident.discovery_event
        else None,
        identity_status=incident.discovery_event.identity_status
        if incident.discovery_event
        else None,
        association_reasons=list(incident.discovery_event.association_reasons)
        if incident.discovery_event
        else [],
        discovery_reports=[
            DiscoveryReportResponse(
                source=_source_response(report.article.source),
                original_url=report.article.original_url,
                indexed_at=report.article.indexed_at,
                event_time=report.mention.time.start
                if report.mention and report.mention.time
                else report.article.event_time,
                mention_id=report.mention.mention_id if report.mention else None,
                mention_excerpt=report.mention.text if report.mention else None,
                mention_role=report.mention.role if report.mention else "reported",
                event_date_wording=report.mention.time.wording
                if report.mention and report.mention.time
                else None,
                event_date_precision=report.mention.time.precision
                if report.mention and report.mention.time
                else "unknown",
                event_date_end=report.mention.time.end
                if report.mention and report.mention.time
                else None,
                event_year_inferred=report.mention.time.year_inferred
                if report.mention and report.mention.time
                else False,
                location_precision=report.mention.place.precision
                if report.mention and report.mention.place
                else "unresolved",
                mention_notices=list(report.mention.notices) if report.mention else [],
                episode_account=_episode_response(report.mention.episode_account)
                if report.mention
                else None,
                origin=report.article.origin,
                fatality_evidence=list(
                    (
                        claim.excerpt
                        for claim in report.mention.claims
                        if claim.fact.category == "fatalities"
                    )
                    if report.mention
                    else fatality_accounts(report.article, report.disaster)
                ),
                claims=[
                    _impact_response(claim)
                    for claim in (
                        report.mention.claims
                        if report.mention
                        else extract_reported_impacts(
                            scoped_disaster_text(
                                report.article.text,
                                report.article.source.title,
                                report.disaster,
                            ),
                            report.article.source,
                            location=report.article.location,
                        )
                    )
                ],
                location=report.mention.place.wording
                if report.mention and report.mention.place
                else report.article.location,
                geometry=_event_geometry_response(
                    report.mention.geometry
                    if report.mention
                    else report.article.geometry
                ),
                access_issue=report.article.access_issue
                or (
                    "Article content was not available for extraction."
                    if not report.article.text
                    else None
                ),
            )
            for report in incident.discovery_event.reports
        ]
        if incident.discovery_event
        else [],
        collection_notices=[
            (
                "Only collected reports are shown. Discovery has bounded "
                "article and query budgets; coverage is not exhaustive."
            ),
            (
                "Impact extraction uses English source sentences up to 600 "
                "characters from retained text (at most 20,000 characters "
                "per article); missing claims remain unknown."
            ),
            (
                "Structured impacts exclude explicit competing causes and other "
                "hazards. Broad multi-topic reports require a hazard-linked "
                "sentence; unscoped accounts remain unknown. Source links are retained."
            ),
            *incident.discovery_event.collection_notices,
        ]
        if incident.discovery_event
        else [],
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
