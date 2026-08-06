"""Current-disaster workflow orchestration."""

from collections.abc import Callable
from datetime import UTC, datetime

from disaster_monitor.application.disaster import (
    DisasterQuery,
    DisasterReport,
    ProviderBatch,
    ReportSection,
    SelectedEventSummary,
)
from disaster_monitor.application.ports.disaster_information import (
    DisasterEventProvider,
    SituationReportProvider,
)
from disaster_monitor.application.services.disaster_report_renderer import (
    DisasterReportRenderer,
)
from disaster_monitor.application.services.event_resolution import (
    EventPolicyRegistry,
    EventResolution,
    default_event_policy_registry,
)
from disaster_monitor.application.services.evidence_reconciliation import (
    EvidenceReconciler,
)
from disaster_monitor.application.services.provider_registry import (
    ProviderRegistry,
    ProviderRole,
)
from disaster_monitor.domain.disaster import DisasterEvent, SituationReport


def _now_utc() -> datetime:
    return datetime.now(UTC)


def _as_batch[T](result: ProviderBatch[T] | tuple[T, ...]) -> ProviderBatch[T]:
    if isinstance(result, ProviderBatch):
        return result
    return ProviderBatch(records=tuple(result))


def _format_timestamp(value: datetime | None) -> str:
    if value is None:
        return "unknown time"
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


class CurrentDisasterReportService:
    """Coordinate provider selection, event resolution, evidence, and rendering."""

    def __init__(
        self,
        event_provider: DisasterEventProvider,
        situation_report_provider: SituationReportProvider,
        *,
        provider_registry: ProviderRegistry | None = None,
        event_policies: EventPolicyRegistry | None = None,
        evidence_reconciler: EvidenceReconciler | None = None,
        renderer: DisasterReportRenderer | None = None,
        clock: Callable[[], datetime] = _now_utc,
    ) -> None:
        self._event_provider = event_provider
        self._situation_report_provider = situation_report_provider
        self._provider_registry = provider_registry
        self._event_policies = event_policies or default_event_policy_registry()
        self._evidence_reconciler = evidence_reconciler or EvidenceReconciler()
        self._renderer = renderer or DisasterReportRenderer()
        self._clock = clock

    async def execute(self, query: DisasterQuery) -> DisasterReport:
        retrieved_at = self._clock()
        if retrieved_at.tzinfo is None:
            retrieved_at = retrieved_at.replace(tzinfo=UTC)
        warnings: list[str] = []
        if self._provider_registry is not None:
            event_selection = self._provider_registry.select(
                query, ProviderRole.EVENT_DISCOVERY
            )
            if not event_selection.registrations:
                return self._coverage_unavailable_report(
                    query,
                    retrieved_at,
                    event_selection.unavailable_configuration,
                )
            warnings.extend(
                f"{name} is unavailable because required configuration is missing."
                for name in event_selection.unavailable_configuration
            )
        event_batch = ProviderBatch[DisasterEvent]()
        try:
            event_batch = _as_batch(
                await self._event_provider.find_recent_events(query, now=retrieved_at)
            )
        except Exception:
            warnings.append(
                f"A {query.hazard.value} event source could not be reached or "
                "returned invalid data."
            )
        warnings.extend(issue.message for issue in event_batch.issues)
        if not event_batch.records:
            return self._verification_failed_report(query, retrieved_at, warnings)

        event_policy = self._event_policies.for_hazard(query.hazard)
        clustered_events = event_policy.cluster(event_batch.records)
        resolution = event_policy.resolve(clustered_events, query, now=retrieved_at)
        if resolution.selected is None:
            return self._ambiguous_report(query, resolution, retrieved_at, warnings)
        if resolution.ambiguous:
            warnings.append(
                f"Multiple recent {query.hazard.value} events in "
                f"{query.country.canonical_name} were plausible; this report covers "
                "the highest-ranked candidate."
            )
        event = resolution.selected
        situation_batch = ProviderBatch[SituationReport]()
        situation_available = True
        if self._provider_registry is not None:
            situation_selection = self._provider_registry.select(
                query, ProviderRole.SITUATION_EVIDENCE, event=event
            )
            warnings.extend(
                f"{name} is unavailable because required configuration is missing."
                for name in situation_selection.unavailable_configuration
            )
            situation_available = bool(situation_selection.registrations)
            if not situation_available:
                warnings.append(
                    "No configured source-backed situation provider supports "
                    f"{query.hazard.value} in {query.country.canonical_name}; "
                    "the verified event is reported with partial coverage."
                )
        if situation_available:
            try:
                situation_batch = _as_batch(
                    await self._situation_report_provider.get_situation_reports(
                        event, query, now=retrieved_at
                    )
                )
            except Exception:
                warnings.append(
                    "The situation-report source could not be reached or returned "
                    "invalid data."
                )
        warnings.extend(issue.message for issue in situation_batch.issues)
        packet = self._evidence_reconciler.build(
            query,
            event,
            situation_batch.records,
            warnings=tuple(dict.fromkeys(warnings)),
            retrieved_at=retrieved_at,
        )
        message, sections = self._renderer.render(packet)
        return DisasterReport(
            message=message,
            response_type="current_disaster",
            selected_event=SelectedEventSummary(
                event_id=event.event_id,
                hazard=event.hazard,
                location=event.location,
                event_time=event.event_time,
                magnitude=event.magnitude,
                intensity=event.intensity,
                depth_km=event.depth_km,
                source=event.source,
                provider_ids=event.provider_ids,
            ),
            retrieval_time=retrieved_at,
            sources=packet.sources,
            warnings=packet.warnings,
            sections=sections,
            partial=packet.partial,
        )

    @staticmethod
    def _coverage_unavailable_report(
        query: DisasterQuery,
        retrieved_at: datetime,
        unavailable_configuration: tuple[str, ...],
    ) -> DisasterReport:
        configured_detail = ""
        if unavailable_configuration:
            configured_detail = (
                " Relevant providers unavailable due to configuration: "
                + ", ".join(unavailable_configuration)
                + "."
            )
        content = (
            f"I recognized a request for current {query.hazard.value} information "
            f"in {query.country.canonical_name}, but no configured source-backed "
            "event provider supports this combination."
            f"{configured_detail} No live factual claim is being made."
        )
        sections = (
            ReportSection("Situation summary", content),
            ReportSection(
                "Uncertainties and information gaps",
                "Event verification is unavailable, so damage, impact, and response "
                "claims are intentionally omitted.",
            ),
            ReportSection(
                "Report freshness",
                f"Coverage checked at {_format_timestamp(retrieved_at)}.",
            ),
        )
        return DisasterReport(
            message="\n\n".join(
                f"## {section.title}\n{section.content}" for section in sections
            ),
            response_type="current_disaster_coverage_unavailable",
            selected_event=None,
            retrieval_time=retrieved_at,
            sources=(),
            warnings=tuple(
                f"{name} requires configuration." for name in unavailable_configuration
            ),
            sections=sections,
            partial=True,
        )

    @staticmethod
    def _verification_failed_report(
        query: DisasterQuery, retrieved_at: datetime, warnings: list[str]
    ) -> DisasterReport:
        content = (
            f"I could not verify a matching recent {query.hazard.value} event in "
            f"{query.country.canonical_name} from the configured sources."
        )
        sections = (
            ReportSection("Situation summary", content),
            ReportSection(
                "Uncertainties and information gaps",
                "No current event evidence was available, so no damage, impact, or "
                "response claim is presented.",
            ),
            ReportSection(
                "Report freshness",
                f"Lookup attempted at {_format_timestamp(retrieved_at)}.",
            ),
        )
        return DisasterReport(
            message="\n\n".join(
                f"## {section.title}\n{section.content}" for section in sections
            ),
            response_type="current_disaster_verification_failed",
            selected_event=None,
            retrieval_time=retrieved_at,
            sources=(),
            warnings=tuple(dict.fromkeys(warnings)),
            sections=sections,
            partial=True,
        )

    @staticmethod
    def _ambiguous_report(
        query: DisasterQuery,
        resolution: EventResolution,
        retrieved_at: datetime,
        warnings: list[str],
    ) -> DisasterReport:
        candidates = "; ".join(
            f"{event.location} at {_format_timestamp(event.event_time)}"
            for event in resolution.alternatives
        )
        content = (
            f"I found multiple unrelated recent {query.hazard.value} events in "
            f"{query.country.canonical_name} and cannot safely choose one. "
            f"Possible alternatives include {candidates or 'more than one event'}. "
            "Please provide a date, location, coordinate, severity, or event "
            "identifier."
        )
        sections = (
            ReportSection("Situation summary", content),
            ReportSection(
                "Report freshness",
                f"Lookup attempted at {_format_timestamp(retrieved_at)}.",
            ),
        )
        return DisasterReport(
            message=(
                f"## Situation summary\n{content}\n\n## Report freshness\n"
                f"{sections[1].content}"
            ),
            response_type="current_disaster_ambiguous",
            selected_event=None,
            retrieval_time=retrieved_at,
            sources=(),
            warnings=tuple(dict.fromkeys((*warnings, resolution.rationale))),
            sections=sections,
            partial=True,
        )

    async def aclose(self) -> None:
        """Close live provider clients when the application shuts down."""
        close = getattr(self._event_provider, "aclose", None)
        if close is not None:
            await close()
        close = getattr(self._situation_report_provider, "aclose", None)
        if close is not None:
            await close()
