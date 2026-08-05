"""Current-disaster orchestration and deterministic source-backed reporting."""

from collections.abc import Callable, Iterable
from datetime import UTC, datetime

from disaster_monitor.application.disaster import (
    DisasterEvent,
    DisasterReport,
    EvidencePacket,
    FactStatus,
    ProviderBatch,
    ReportedFact,
    ReportSection,
    SelectedEventSummary,
    SituationReport,
    SourceReference,
)
from disaster_monitor.application.ports.disaster_information import (
    DisasterEventProvider,
    SituationReportProvider,
)
from disaster_monitor.application.services.disaster_query import extract_disaster_query
from disaster_monitor.application.services.event_resolution import (
    EventResolution,
    resolve_recent_event,
)
from disaster_monitor.application.services.evidence_reconciliation import (
    build_evidence_packet,
)
from disaster_monitor.domain.errors import InvalidQuestionError


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


def _citation(source: SourceReference) -> str:
    return f"{source.publisher} — {source.title} ({source.canonical_url})"


def _fact_lines(facts: Iterable[ReportedFact], categories: set[str]) -> list[str]:
    lines: list[str] = []
    for fact in facts:
        if fact.category not in categories:
            continue
        status = (
            "" if fact.status == FactStatus.CONFIRMED else f" ({fact.status.value})"
        )
        lines.append(
            f"- {fact.label}: {fact.value}{status}. Source: {_citation(fact.source)}"
        )
    return lines


def _event_summary(event: DisasterEvent) -> str:
    location = (
        event.location
        if "japan" in event.location.lower()
        else f"{event.location}, Japan"
    )
    details = [
        location,
        f"event time {_format_timestamp(event.event_time)}",
    ]
    if event.magnitude is not None:
        magnitude_type = f" {event.magnitude_type}" if event.magnitude_type else ""
        details.append(f"magnitude {event.magnitude:g}{magnitude_type}")
    if event.intensity:
        details.append(f"maximum intensity {event.intensity}")
    if event.depth_km is not None:
        details.append(f"depth {event.depth_km:g} km")
    return "; ".join(details) + f". Source: {_citation(event.source)}"


def render_source_backed_report(
    packet: EvidencePacket,
) -> tuple[str, tuple[ReportSection, ...]]:
    """Render only normalized evidence; never infer zeros from missing fields."""
    facts = packet.facts
    human_categories = {"fatalities", "injuries", "missing", "evacuations", "shelters"}
    physical_categories = {
        "buildings",
        "fires",
        "landslides",
        "roads",
        "rail",
        "airports",
        "ports",
        "utilities",
        "communications",
        "critical_facilities",
        "damage_status",
    }
    secondary_categories = {"tsunami", "fires", "landslides"}
    response_categories = {"response", "government_response", "emergency_response"}
    human_lines = _fact_lines(facts, human_categories)
    physical_lines = _fact_lines(facts, physical_categories)
    secondary_lines = _fact_lines(facts, secondary_categories)
    response_lines = _fact_lines(facts, response_categories)
    summary = (
        "The selected event is the recent earthquake identified as "
        f"{packet.event.event_id}. "
        f"Retrieved evidence covers {_event_summary(packet.event)}. "
        "The report below separates confirmed, preliminary, estimated, disputed, "
        "and unavailable information."
    )
    sections: list[ReportSection] = [
        ReportSection("Situation summary", summary),
        ReportSection("Event details", _event_summary(packet.event)),
        ReportSection(
            "Human impact",
            "\n".join(human_lines)
            if human_lines
            else (
                "No reliable human-impact figures were found in the retrieved "
                "situation reports; this is not confirmation of zero impact."
            ),
        ),
        ReportSection(
            "Physical and infrastructure damage",
            "\n".join(physical_lines)
            if physical_lines
            else (
                "No reliable damage or infrastructure-disruption figure was found "
                "in the retrieved situation reports; magnitude and shaking alone "
                "were not used to infer damage."
            ),
        ),
        ReportSection(
            "Tsunami and secondary hazards",
            "\n".join(secondary_lines)
            if secondary_lines
            else (
                "No verified tsunami, fire, or landslide impact was found in the "
                "retrieved reports. A warning or advisory alone would not establish "
                "damage."
            ),
        ),
        ReportSection(
            "Emergency and government response",
            "\n".join(response_lines)
            if response_lines
            else (
                "No source-backed government or emergency response action was found "
                "in the retrieved situation reports."
            ),
        ),
    ]
    if packet.conflicts:
        sections.append(
            ReportSection(
                "Uncertainties and information gaps",
                "The following source figures conflict or have not been reconciled: "
                + " ".join(packet.conflicts),
            )
        )
    elif packet.warnings:
        sections.append(
            ReportSection(
                "Uncertainties and information gaps", " ".join(packet.warnings)
            )
        )
    sections.append(
        ReportSection(
            "Sources",
            "\n".join(f"- {_citation(source)}" for source in packet.sources),
        )
    )
    sections.append(
        ReportSection(
            "Report freshness",
            f"Retrieved at {_format_timestamp(packet.retrieved_at)}. "
            + (
                "Some source material is stale relative to this retrieval time."
                if packet.stale
                else "Source retrieval completed within the current report window."
            ),
        )
    )
    message = "\n\n".join(
        f"## {section.title}\n{section.content}" for section in sections
    )
    return message, tuple(sections)


class CurrentDisasterReportService:
    """Coordinate event discovery, selection, evidence, and reporting."""

    def __init__(
        self,
        event_provider: DisasterEventProvider,
        situation_report_provider: SituationReportProvider,
        *,
        clock: Callable[[], datetime] = _now_utc,
    ) -> None:
        self._event_provider = event_provider
        self._situation_report_provider = situation_report_provider
        self._clock = clock

    async def execute(self, question: str) -> DisasterReport:
        query = extract_disaster_query(question)
        if query is None:
            raise InvalidQuestionError(
                "This request is not a supported current-disaster query."
            )
        retrieved_at = self._clock()
        if retrieved_at.tzinfo is None:
            retrieved_at = retrieved_at.replace(tzinfo=UTC)
        warnings: list[str] = []
        event_batch = ProviderBatch[DisasterEvent]()
        try:
            event_batch = _as_batch(
                await self._event_provider.find_recent_events(query, now=retrieved_at)
            )
        except Exception:
            warnings.append(
                "The earthquake event source could not be reached or returned "
                "invalid data."
            )
        warnings.extend(issue.message for issue in event_batch.issues)
        if not event_batch.records:
            sections: tuple[ReportSection, ...] = (
                ReportSection(
                    "Situation summary",
                    "I could not verify a matching recent earthquake in Japan from "
                    "the configured sources.",
                ),
                ReportSection(
                    "Uncertainties and information gaps",
                    "No current event evidence was available, so no damage or "
                    "response claim is presented.",
                ),
                ReportSection(
                    "Report freshness",
                    f"Lookup attempted at {_format_timestamp(retrieved_at)}.",
                ),
            )
            message = "\n\n".join(
                f"## {item.title}\n{item.content}" for item in sections
            )
            return DisasterReport(
                message=message,
                response_type="current_disaster_verification_failed",
                selected_event=None,
                retrieval_time=retrieved_at,
                sources=(),
                warnings=tuple(dict.fromkeys(warnings)),
                sections=sections,
                partial=True,
            )

        resolution = resolve_recent_event(event_batch.records, query, now=retrieved_at)
        if resolution.selected is None:
            return self._ambiguous_report(resolution, retrieved_at, warnings)
        if resolution.ambiguous:
            warnings.append(
                "Multiple recent Japanese earthquakes were plausible; this report "
                "covers the highest-ranked candidate."
            )
        event = resolution.selected
        situation_batch = ProviderBatch[SituationReport]()
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
        packet = build_evidence_packet(
            query,
            event,
            situation_batch.records,
            warnings=tuple(dict.fromkeys(warnings)),
            retrieved_at=retrieved_at,
        )
        message, sections = render_source_backed_report(packet)
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
            ),
            retrieval_time=retrieved_at,
            sources=packet.sources,
            warnings=packet.warnings,
            sections=sections,
            partial=bool(packet.warnings),
        )

    @staticmethod
    def _ambiguous_report(
        resolution: EventResolution,
        retrieved_at: datetime,
        warnings: list[str],
    ) -> DisasterReport:
        candidates = "; ".join(
            f"{event.location} at {_format_timestamp(event.event_time)}"
            for event in resolution.alternatives
        )
        content = (
            "I found multiple unrelated recent earthquakes in Japan and cannot "
            "safely choose one. "
            f"Possible alternatives include {candidates or 'more than one event'}. "
            "Please provide a date, prefecture, city, magnitude, or event identifier."
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
