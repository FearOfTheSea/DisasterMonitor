"""Disaster-neutral deterministic rendering of normalized evidence."""

from collections.abc import Iterable
from datetime import UTC, datetime

from disaster_monitor.application.disaster import EvidencePacket, ReportSection
from disaster_monitor.application.services.report_profiles import (
    ReportProfile,
    report_profile_for,
)
from disaster_monitor.domain.disaster import FactStatus, ReportedFact, SourceReference


def _format_timestamp(value: datetime | None) -> str:
    if value is None:
        return "unknown time"
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _citation(source: SourceReference) -> str:
    return f"{source.publisher} — {source.title} ({source.canonical_url})"


def _fact_lines(facts: Iterable[ReportedFact], categories: frozenset[str]) -> list[str]:
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


def _event_summary(packet: EvidencePacket) -> str:
    event = packet.event
    country_name = packet.query.country.canonical_name
    location = (
        event.location
        if country_name.lower() in event.location.lower()
        else f"{event.location}, {country_name}"
    )
    details = [location, f"event time {_format_timestamp(event.event_time)}"]
    details.extend(
        f"{measurement.kind.value} {measurement.value}"
        + (f" {measurement.unit}" if measurement.unit else "")
        for measurement in event.measurements
    )
    return "; ".join(details) + f". Source: {_citation(event.source)}"


class DisasterReportRenderer:
    """Render only normalized facts using a disaster-selected report profile."""

    def render(
        self,
        packet: EvidencePacket,
        profile: ReportProfile | None = None,
    ) -> tuple[str, tuple[ReportSection, ...]]:
        profile = profile or report_profile_for(packet.query.disaster)
        human_lines = _fact_lines(packet.facts, profile.human_categories)
        physical_lines = _fact_lines(packet.facts, profile.physical_categories)
        response_lines = _fact_lines(packet.facts, profile.response_categories)
        narrative_lines = [f"- {narrative}" for narrative in packet.narratives]
        summary = (
            f"The selected source-backed {packet.query.disaster.value} event is "
            f"{packet.event.event_id}. Retrieved evidence covers "
            f"{_event_summary(packet)}. The report separates confirmed, preliminary, "
            "estimated, disputed, and unavailable information."
        )
        sections: list[ReportSection] = [
            ReportSection("Situation summary", summary),
            ReportSection("Event details", _event_summary(packet)),
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
                    "in the retrieved situation reports; event severity was "
                    "not used to infer damage."
                ),
            ),
        ]
        if narrative_lines:
            sections.append(
                ReportSection("Qualitative source evidence", "\n".join(narrative_lines))
            )
        if profile.secondary_title is not None:
            secondary_lines = _fact_lines(packet.facts, profile.secondary_categories)
            sections.append(
                ReportSection(
                    profile.secondary_title,
                    "\n".join(secondary_lines)
                    if secondary_lines
                    else (profile.secondary_missing or "No verified evidence found."),
                )
            )
        sections.append(
            ReportSection(
                "Emergency and government response",
                "\n".join(response_lines)
                if response_lines
                else (
                    "No source-backed emergency response action was found in the "
                    "retrieved situation reports."
                ),
            )
        )
        gaps = []
        if packet.conflicts:
            gaps.append(
                "The following source figures conflict or remain unreconciled: "
                + " ".join(packet.conflicts)
            )
        if packet.warnings:
            gaps.append(" ".join(packet.warnings))
        if gaps:
            sections.append(
                ReportSection("Uncertainties and information gaps", " ".join(gaps))
            )
        sections.extend(
            (
                ReportSection(
                    "Sources",
                    "\n".join(f"- {_citation(source)}" for source in packet.sources),
                ),
                ReportSection(
                    "Report freshness",
                    f"Retrieved at {_format_timestamp(packet.retrieved_at)}. "
                    + (
                        "Some source material is stale relative to this retrieval time."
                        if packet.stale
                        else (
                            "Source retrieval completed within the current report "
                            "window."
                        )
                    ),
                ),
            )
        )
        message = "\n\n".join(
            f"## {section.title}\n{section.content}" for section in sections
        )
        return message, tuple(sections)


def render_source_backed_report(
    packet: EvidencePacket,
) -> tuple[str, tuple[ReportSection, ...]]:
    """Convenience entry point for deterministic renderer tests."""
    return DisasterReportRenderer().render(packet)
