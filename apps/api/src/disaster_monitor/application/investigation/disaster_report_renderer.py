"""Disaster-neutral deterministic rendering of normalized evidence."""

import re
import unicodedata
from collections.abc import Iterable
from datetime import UTC, datetime

from disaster_monitor.application.disaster import EvidencePacket, ReportSection
from disaster_monitor.application.investigation.report_profiles import (
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


def _fold_place(value: str) -> str:
    unaccented = "".join(
        character
        for character in unicodedata.normalize("NFKD", value.casefold())
        if not unicodedata.combining(character)
    )
    return " ".join(re.sub(r"[^a-z0-9?]+", " ", unaccented).split())


def _place_core(value: str, country: str) -> str:
    folded = _fold_place(value)
    country_suffix = f" {_fold_place(country)}"
    if folded.endswith(country_suffix):
        folded = folded[: -len(country_suffix)].strip()
    return re.sub(r" (?:province|district|city|ward)$", "", folded)


def _fact_matches_named_place(
    fact: ReportedFact, *, place: str, country: str
) -> bool:
    if fact.reported_location is None:
        return True
    wanted = _place_core(place, country)
    actual = _place_core(fact.reported_location, country)
    if not wanted or not actual:
        return False
    if "?" not in actual:
        return actual == wanted
    # One replacement character in a provider label may stand for a lost accent.
    # Keep the source spelling visible when accepting this narrow match.
    if actual.count("?") != 1 or len(wanted) < 5:
        return False
    return bool(re.fullmatch(re.escape(actual).replace(r"\?", "[a-z]"), wanted))


def _scoped_facts(
    packet: EvidencePacket,
) -> tuple[tuple[ReportedFact, ...], tuple[ReportedFact, ...]]:
    if not packet.query.location_hint:
        return packet.facts, ()
    visible: list[ReportedFact] = []
    omitted: list[ReportedFact] = []
    for fact in packet.facts:
        (visible if _fact_matches_named_place(
            fact,
            place=packet.query.location_hint,
            country=packet.query.country.canonical_name,
        ) else omitted).append(fact)
    return tuple(visible), tuple(omitted)


def _measurement_details(packet: EvidencePacket) -> tuple[str, ...]:
    details: list[str] = []
    seen: set[str] = set()
    for measurement in packet.event.measurements:
        detail = f"{measurement.kind.value} {measurement.value}"
        if measurement.unit:
            detail = f"{detail} {measurement.unit}"
        if detail not in seen:
            details.append(f"{detail} (source: {_citation(measurement.source)})")
            seen.add(detail)
    return tuple(details)


def _event_summary(packet: EvidencePacket) -> str:
    event = packet.event
    country_name = packet.query.country.canonical_name
    location = (
        event.location
        if country_name.lower() in event.location.lower()
        else f"{event.location}, {country_name}"
    )
    location_citation = (
        f" Location source: {_citation(event.location_source)}."
        if event.location_source is not None
        else ""
    )
    summary = (
        f"{location}; event time {_format_timestamp(event.event_time)}."
        f"{location_citation} Event source: {_citation(event.source)}"
    )
    measurements = _measurement_details(packet)
    if measurements:
        summary += ". Measurements: " + "; ".join(measurements)
    return summary + "."


class DisasterReportRenderer:
    """Render only normalized facts using a disaster-selected report profile."""

    def render(
        self,
        packet: EvidencePacket,
        profile: ReportProfile | None = None,
    ) -> tuple[str, tuple[ReportSection, ...]]:
        profile = profile or report_profile_for(packet.query.disaster)
        visible_facts, omitted_facts = _scoped_facts(packet)
        place_phrase = " for the requested place" if packet.query.location_hint else ""

        def scoped_lines(categories: frozenset[str], missing: str) -> str:
            lines = _fact_lines(visible_facts, categories)
            omitted_count = sum(
                fact.category in categories for fact in omitted_facts
            )
            content = "\n".join(lines) if lines else missing
            if omitted_count:
                content += (
                    f"\n{omitted_count} other-area or country-wide reported "
                    "figures were omitted for the requested place."
                )
            return content

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
                scoped_lines(
                    profile.human_categories,
                    "No reliable human-impact figures were found in the retrieved "
                    f"situation reports{place_phrase}; this is not confirmation "
                    "of zero impact.",
                ),
            ),
            ReportSection(
                "Physical and infrastructure damage",
                scoped_lines(
                    profile.physical_categories,
                    "No reliable damage or infrastructure-disruption figure was found "
                    f"in the retrieved situation reports{place_phrase}; event "
                    "severity was not used to infer damage.",
                ),
            ),
        ]
        if narrative_lines:
            sections.append(
                ReportSection("Qualitative source evidence", "\n".join(narrative_lines))
            )
        if profile.secondary_title is not None:
            sections.append(
                ReportSection(
                    profile.secondary_title,
                    scoped_lines(
                        profile.secondary_categories,
                        profile.secondary_missing or "No verified evidence found.",
                    ),
                )
            )
        sections.append(
            ReportSection(
                "Emergency and government response",
                scoped_lines(
                    profile.response_categories,
                    "No source-backed emergency response action was found in the "
                    f"retrieved situation reports{place_phrase}.",
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
