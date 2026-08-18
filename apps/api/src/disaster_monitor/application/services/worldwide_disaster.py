"""Capability-selected orchestration for bounded worldwide disaster lookups."""

from collections.abc import Callable
from datetime import UTC, datetime
from typing import cast

from disaster_monitor.application.disaster import (
    DisasterReport,
    ProviderBatch,
    ReportSection,
    SelectedEventSummary,
    WorldwideDisasterEvent,
    WorldwideDisasterQuery,
)
from disaster_monitor.application.ports.disaster_information import (
    WorldwideDisasterProvider,
)
from disaster_monitor.application.services.provider_registry import (
    ProviderRegistry,
    ProviderRole,
)
from disaster_monitor.application.services.source_evidence_policy import (
    SourceEvidencePolicyError,
    validate_worldwide_event_evidence,
)
from disaster_monitor.application.services.worldwide_disaster_policy import (
    WorldwideDisasterPolicyRegistry,
    default_worldwide_disaster_policy_registry,
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
        if len(selection.registrations) != 1:
            detail = (
                "I could not verify a matching worldwide event because worldwide "
                "provider authority is unavailable or ambiguous."
            )
            return _failed_report(detail, now, warnings)
        registration = selection.registrations[0]
        if not registration.source_id or not registration.allowed_hosts:
            return _failed_report(
                "I could not verify a matching worldwide event because the selected "
                "provider has incomplete source authority.",
                now,
                warnings,
            )
        provider = registration.provider
        if not callable(getattr(provider, "find_worldwide_events", None)):
            return _failed_report(
                "I could not verify a matching worldwide event because the selected "
                "provider cannot execute worldwide queries.",
                now,
                warnings,
            )
        try:
            raw_batch = await cast(
                WorldwideDisasterProvider, provider
            ).find_worldwide_events(query, now=now)
            batch = (
                raw_batch
                if isinstance(raw_batch, ProviderBatch)
                else ProviderBatch(tuple(raw_batch))
            )
        except Exception:
            batch = ProviderBatch()
            warnings.append(
                "The worldwide disaster source could not be reached or "
                "returned invalid data."
            )
        accepted: list[WorldwideDisasterEvent] = []
        for record in batch.records:
            try:
                accepted.append(
                    validate_worldwide_event_evidence(
                        record,
                        query,
                        source_id=registration.source_id,
                        allowed_hosts=registration.allowed_hosts,
                    )
                )
            except SourceEvidencePolicyError:
                warnings.append(
                    "A worldwide disaster record violated source policy and was "
                    "excluded."
                )
        warnings.extend(issue.message for issue in batch.issues)
        policy = self._policies.for_hazard(query.hazard)
        selected = policy.select(tuple(accepted), query)
        if selected is None:
            return _failed_report(
                "I could not verify a matching worldwide event from the configured "
                "source within the bounded search window.",
                now,
                warnings,
            )
        summary = SelectedEventSummary(
            event_id=selected.event_id,
            hazard=selected.hazard,
            location=selected.location,
            event_time=selected.event_time,
            latitude=selected.latitude,
            longitude=selected.longitude,
            magnitude=selected.magnitude,
            intensity=selected.intensity,
            depth_km=selected.depth_km,
            source=selected.source,
            provider_ids=selected.provider_ids,
        )
        detail = policy.describe_selection(selected, query)
        limitation = (
            "This worldwide capability verifies source-backed event data only. "
            "It does not claim globally complete casualties, damage, warnings, or "
            "response information."
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
            sources=(selected.source,),
            warnings=tuple(dict.fromkeys(warnings)),
            sections=sections,
            partial=True,
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
    )


def _utc_text(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
