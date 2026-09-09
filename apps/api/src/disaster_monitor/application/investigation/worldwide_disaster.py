"""Capability-selected orchestration for bounded worldwide disaster lookups."""

from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime
from typing import Protocol

from disaster_monitor.application.disaster import (
    DisasterReport,
    ProviderBatch,
    ReportSection,
    SelectedEventSummary,
    WorldwideDisasterEvent,
    WorldwideDisasterQuery,
)
from disaster_monitor.application.evidence.source_evidence_policy import (
    validate_worldwide_event_evidence,
    validate_worldwide_situation_evidence,
)
from disaster_monitor.application.incidents.models import (
    ActiveIncident,
    ActiveIncidentsQuery,
    ActiveIncidentsSnapshot,
)
from disaster_monitor.application.investigation.worldwide_disaster_policy import (
    WorldwideDisasterPolicyRegistry,
    default_worldwide_disaster_policy_registry,
)
from disaster_monitor.application.ports.source_evidence import (
    SourceEvidencePolicyError,
)
from disaster_monitor.application.sources.provider_registry import (
    ProviderRegistry,
    ProviderRole,
)
from disaster_monitor.domain.disaster import (
    CycloneMapLayer,
    EventGeographyStatus,
    ProviderTier,
    SituationReport,
)
from disaster_monitor.domain.news import IncidentCandidateStatus


def _now_utc() -> datetime:
    return datetime.now(UTC)


class ProjectedIncidentReader(Protocol):
    async def execute(
        self, query: ActiveIncidentsQuery | None = None
    ) -> ActiveIncidentsSnapshot: ...


class WorldwideDisasterReportService:
    """Execute one explicitly worldwide query through registry capabilities."""

    def __init__(
        self,
        provider_registry: ProviderRegistry,
        *,
        policies: WorldwideDisasterPolicyRegistry | None = None,
        clock: Callable[[], datetime] = _now_utc,
        incident_reader: ProjectedIncidentReader | None = None,
    ) -> None:
        self._provider_registry = provider_registry
        self._policies = policies or default_worldwide_disaster_policy_registry()
        self._clock = clock
        self._incident_reader = incident_reader

    async def execute(self, query: WorldwideDisasterQuery) -> DisasterReport:
        now = self._clock()
        if self._incident_reader is not None:
            snapshot = await self._incident_reader.execute(
                ActiveIncidentsQuery(
                    time_window_days=min(query.time_window_days, 30),
                    hazard=query.disaster,
                )
            )
            projected = self._policies.for_disaster(query.disaster).select(
                tuple(_worldwide_event(item) for item in snapshot.incidents), query
            )
            if projected is not None:
                incident = next(
                    item
                    for item in snapshot.incidents
                    if item.event_id == projected.event_id
                )
                return _projected_report(incident, query, now, self._policies)
        warnings: list[str] = []
        selection = self._provider_registry.select(query, ProviderRole.EVENT_DISCOVERY)
        if not selection.registrations:
            detail = (
                "I could not verify a matching worldwide event because worldwide "
                "provider authority is unavailable or ambiguous."
            )
            return _failed_report(detail, now, warnings)
        accepted_by_tier: dict[ProviderTier, list[WorldwideDisasterEvent]] = {}
        event_actions: list[str] = []
        for registration in selection.registrations:
            provider = registration.worldwide_provider
            if (
                not registration.source_id
                or not registration.allowed_hosts
                or provider is None
            ):
                warnings.append(
                    f"Worldwide provider {registration.name} has incomplete "
                    "executable authority."
                )
                continue
            try:
                raw_batch = await provider.find_worldwide_events(query, now=now)
                batch = (
                    raw_batch
                    if isinstance(raw_batch, ProviderBatch)
                    else ProviderBatch(tuple(raw_batch))
                )
            except Exception:
                batch = ProviderBatch()
                warnings.append(
                    f"Worldwide provider {registration.name} could not be reached "
                    "or returned invalid data."
                )
            for event_record in batch.records:
                try:
                    validated_event = validate_worldwide_event_evidence(
                        event_record,
                        query,
                        source_id=registration.source_id,
                        allowed_hosts=registration.allowed_hosts,
                    )
                    accepted_by_tier.setdefault(registration.tier, []).append(
                        validated_event
                    )
                except SourceEvidencePolicyError:
                    warnings.append(
                        "A worldwide disaster record violated source policy and was "
                        "excluded."
                    )
            warnings.extend(issue.message for issue in batch.issues)
            event_actions.append(
                f"Queried worldwide event provider {registration.name}."
            )
        policy = self._policies.for_disaster(query.disaster)
        highest_available_tier = max(
            accepted_by_tier,
            key=lambda tier: tier.precedence,
            default=None,
        )
        tier_events = (
            tuple(accepted_by_tier[highest_available_tier])
            if highest_available_tier is not None
            else ()
        )
        selected = policy.select(tier_events, query)
        if selected is None:
            return _failed_report(
                "I could not verify a matching worldwide event from the configured "
                "source within the bounded search window.",
                now,
                warnings,
            )
        summary = SelectedEventSummary(
            event_id=selected.event_id,
            disaster=selected.disaster,
            location=selected.location,
            event_time=selected.event_time,
            geometry=selected.geometry,
            measurements=selected.measurements,
            source=selected.source,
            provider_ids=selected.provider_ids,
            lineage_ids=selected.lineage_ids,
            geography_status=EventGeographyStatus.WORLDWIDE,
        )
        detail = policy.describe_selection(selected, query)
        situation_selection = self._provider_registry.select(
            query, ProviderRole.SITUATION_EVIDENCE
        )
        situation_reports: list[SituationReport] = []
        situation_actions: list[str] = []
        for registration in situation_selection.registrations:
            situation_provider = registration.worldwide_situation_provider
            if (
                not registration.source_id
                or not registration.allowed_hosts
                or situation_provider is None
            ):
                continue
            try:
                raw_situation_batch = (
                    await situation_provider.get_worldwide_situation_reports(
                        selected, query, now=now
                    )
                )
                situation_batch = (
                    raw_situation_batch
                    if isinstance(raw_situation_batch, ProviderBatch)
                    else ProviderBatch(tuple(raw_situation_batch))
                )
            except Exception:
                situation_batch = ProviderBatch()
                warnings.append(
                    f"Worldwide situation provider {registration.name} could not "
                    "be reached."
                )
            for situation_record in situation_batch.records:
                try:
                    situation_reports.append(
                        validate_worldwide_situation_evidence(
                            situation_record,
                            query,
                            source_id=registration.source_id,
                            allowed_hosts=registration.allowed_hosts,
                        )
                    )
                except SourceEvidencePolicyError:
                    warnings.append(
                        "A worldwide situation record violated source policy and "
                        "was excluded."
                    )
            warnings.extend(issue.message for issue in situation_batch.issues)
            situation_actions.append(
                f"Queried worldwide situation provider {registration.name}."
            )
        capability_gaps = []
        if not situation_selection.registrations:
            capability_gaps.append(
                "No worldwide situation-evidence capability is configured."
            )
        elif not situation_reports:
            capability_gaps.append(
                "Configured worldwide situation sources returned no usable evidence."
            )
        complete = bool(situation_reports) and not capability_gaps
        summary = replace(
            summary,
            supplemental_geometry=_supplemental_geometry(tuple(situation_reports)),
        )
        limitation = (
            "Worldwide event and situation evidence were obtained from configured "
            "sources."
            if complete
            else "This worldwide capability does not establish complete global "
            "impact coverage."
        )
        source_line = (
            f"{selected.source.publisher} - {selected.source.title} "
            f"({selected.source.canonical_url})"
        )
        sections = (
            ReportSection("Situation summary", detail),
            ReportSection("Coverage boundary", limitation),
            ReportSection("Sources", f"- {source_line}"),
            ReportSection("Report freshness", f"Retrieved at {_utc_text(now)}."),
        )
        return DisasterReport(
            message="\n\n".join(
                f"## {section.title}\n{section.content}" for section in sections
            ),
            response_type=policy.response_type(query),
            selected_event=summary,
            retrieval_time=now,
            sources=(selected.source, *(report.source for report in situation_reports)),
            warnings=tuple(dict.fromkeys(warnings)),
            sections=sections,
            partial=not complete,
            capability_gaps=tuple(capability_gaps),
            investigation_actions=tuple(
                (
                    *event_actions,
                    "Selected and rendered one source-backed worldwide event.",
                    *situation_actions,
                )
            ),
            termination_reason=(
                "completed_worldwide_evidence"
                if complete
                else "partial_worldwide_event_evidence"
            ),
        )


def _failed_report(detail: str, now: datetime, warnings: list[str]) -> DisasterReport:
    section = ReportSection("Situation summary", detail)
    return DisasterReport(
        message=f"## Situation summary\n{detail}",
        response_type="current_disaster_worldwide_verification_failed",
        selected_event=None,
        retrieval_time=now,
        sources=(),
        warnings=tuple(dict.fromkeys(warnings)),
        sections=(section,),
        partial=True,
        capability_gaps=("Worldwide event discovery is unavailable.",),
        investigation_actions=("Attempted the configured worldwide event lookup.",),
        termination_reason="worldwide_event_verification_failed",
    )


def _worldwide_event(incident: ActiveIncident) -> WorldwideDisasterEvent:
    return WorldwideDisasterEvent(
        event_id=incident.event_id,
        disaster=incident.disaster,
        location=incident.location,
        event_time=incident.event_time,
        source=incident.source,
        geometry=incident.geometry,
        measurements=incident.measurements,
        provider_ids=incident.provider_ids,
        lineage_ids=incident.lineage_ids,
        observation_kind=incident.observation_kind,
        activity_status=incident.activity_status,
    )


def _projected_report(
    incident: ActiveIncident,
    query: WorldwideDisasterQuery,
    now: datetime,
    policies: WorldwideDisasterPolicyRegistry,
) -> DisasterReport:
    event = _worldwide_event(incident)
    summary = SelectedEventSummary(
        event_id=event.event_id,
        disaster=event.disaster,
        location=event.location,
        event_time=event.event_time,
        geometry=event.geometry,
        measurements=event.measurements,
        source=event.source,
        provider_ids=event.provider_ids,
        lineage_ids=event.lineage_ids,
        geography_status=EventGeographyStatus.WORLDWIDE,
    )
    provisional = (
        incident.verification_status
        is IncidentCandidateStatus.PROVISIONAL_NEWS_DETECTED
    )
    status = (
        "Provisional — a major-news report was detected; authoritative-source "
        "confirmation is pending."
        if provisional
        else "This incident is source-backed in the shared monitoring projection."
    )
    detail = policies.for_disaster(query.disaster).describe_selection(event, query)
    source_lines = "\n".join(
        f"- {source.publisher} - {source.title} ({source.canonical_url})"
        for source in incident.evidence_sources or (incident.source,)
    )
    sections = (
        ReportSection("Verification status", status),
        ReportSection("Situation summary", detail),
        ReportSection("Sources", source_lines),
        ReportSection("Projection freshness", f"Retrieved at {_utc_text(now)}."),
    )
    return DisasterReport(
        message="\n\n".join(
            f"## {section.title}\n{section.content}" for section in sections
        ),
        response_type=(
            "current_disaster_worldwide_provisional"
            if provisional
            else policies.for_disaster(query.disaster).response_type(query)
        ),
        selected_event=summary,
        retrieval_time=now,
        sources=incident.evidence_sources or (incident.source,),
        warnings=((status,) if provisional else ()),
        sections=sections,
        partial=True,
        capability_gaps=(
            ("Authoritative corroboration is pending.",) if provisional else ()
        ),
        investigation_actions=("Read the shared durable incident projection.",),
        termination_reason=(
            "provisional_news_detected" if provisional else "projected_incident_found"
        ),
    )


def _supplemental_geometry(
    reports: tuple[SituationReport, ...],
) -> tuple[CycloneMapLayer, ...]:
    layers = {
        layer.layer_id: layer
        for report in reports
        for layer in report.supplemental_geometry
    }
    return tuple(layers[layer_id] for layer_id in sorted(layers))


def _utc_text(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
