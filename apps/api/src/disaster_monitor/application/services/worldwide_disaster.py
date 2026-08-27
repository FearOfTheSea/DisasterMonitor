"""Capability-selected orchestration for bounded worldwide disaster lookups."""

from collections.abc import Callable
from datetime import UTC, datetime

from disaster_monitor.application.disaster import (
    DisasterReport,
    ProviderBatch,
    ReportSection,
    SelectedEventSummary,
    WorldwideDisasterEvent,
    WorldwideDisasterQuery,
)
from disaster_monitor.application.ports.source_evidence import (
    SourceEvidencePolicyError,
)
from disaster_monitor.application.services.provider_registry import (
    ProviderRegistry,
    ProviderRole,
)
from disaster_monitor.application.services.source_evidence_policy import (
    validate_worldwide_event_evidence,
    validate_worldwide_situation_evidence,
)
from disaster_monitor.application.services.worldwide_disaster_policy import (
    WorldwideDisasterPolicyRegistry,
    default_worldwide_disaster_policy_registry,
)
from disaster_monitor.domain.disaster import (
    EventGeographyStatus,
    ProviderTier,
    SituationReport,
)


def _now_utc() -> datetime:
    return datetime.now(UTC)


class WorldwideDisasterReportService:
    """Execute one explicitly worldwide query through registry capabilities."""

    def __init__(
        self,
        provider_registry: ProviderRegistry,
        *,
        policies: WorldwideDisasterPolicyRegistry | None = None,
        clock: Callable[[], datetime] = _now_utc,
    ) -> None:
        self._provider_registry = provider_registry
        self._policies = policies or default_worldwide_disaster_policy_registry()
        self._clock = clock

    async def execute(self, query: WorldwideDisasterQuery) -> DisasterReport:
        now = self._clock()
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


def _utc_text(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
