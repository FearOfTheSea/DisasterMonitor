"""Disaster-neutral deterministic rendering of normalized evidence."""

import re
import unicodedata
from collections.abc import Iterable
from datetime import UTC, datetime

from disaster_monitor.application.disaster import EvidencePacket, ReportSection
from disaster_monitor.application.disaster_aliases import recognized_disasters
from disaster_monitor.application.investigation.report_profiles import (
    ReportProfile,
    report_profile_for,
)
from disaster_monitor.domain.disaster import (
    EventMeasurement,
    FactStatus,
    MeasurementKind,
    ReportedFact,
    SourceReference,
)


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


def _fact_matches_named_place(fact: ReportedFact, *, place: str, country: str) -> bool:
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
        (
            visible
            if _fact_matches_named_place(
                fact,
                place=packet.query.location_hint,
                country=packet.query.country.canonical_name,
            )
            else omitted
        ).append(fact)
    return tuple(visible), tuple(omitted)


def _measurement_details(packet: EvidencePacket) -> tuple[str, ...]:
    details: list[str] = []
    seen: set[str] = set()
    for measurement in packet.event.measurements:
        label = _measurement_label(measurement.kind, measurement.source)
        detail = f"{label} {measurement.value}"
        if measurement.unit:
            detail = f"{detail} {measurement.unit}"
        if detail not in seen:
            details.append(f"{detail} (source: {_citation(measurement.source)})")
            seen.add(detail)
    return tuple(details)


def _measurement_label(kind: MeasurementKind, source: SourceReference) -> str:
    if kind is MeasurementKind.SEVERITY and source.source_id.startswith("gdacs-"):
        return "GDACS alert level"
    if kind is MeasurementKind.MAXIMUM_WIND_SPEED and source.source_id.startswith(
        "gdacs-"
    ):
        return "GDACS maximum wind-speed estimate"
    return kind.value.replace("_", " ")


def _situation_summary(
    packet: EvidencePacket,
    visible_facts: tuple[ReportedFact, ...],
    profile: ReportProfile,
) -> str:
    title = " ".join(packet.event.source.title.split())
    named_hazard = recognized_disasters(title) == (packet.query.disaster,)
    if not named_hazard and not (
        packet.query.disaster.value == "volcanic_eruption"
        and "eruption" in title.casefold()
    ):
        title = f"{packet.query.disaster.value.replace('_', ' ').capitalize()}: {title}"
    event_location = " ".join(packet.event.location.split())
    location = event_location
    country = packet.query.country.canonical_name
    if country.casefold() not in location.casefold():
        location = f"{location}, {country}"
    if _fold_place(event_location) in _fold_place(title):
        if _fold_place(country) not in _fold_place(title):
            title = f"{title}, {country}"
    else:
        title = f"{title} — {location}"
    event_time = packet.event.event_time.astimezone(UTC)
    parts = [f"{title}; {event_time.day} {event_time:%b %Y, %H:%M} UTC."]
    measurements_by_kind: dict[MeasurementKind, EventMeasurement] = {}
    for measurement in packet.event.measurements:
        if measurement.kind not in {
            MeasurementKind.MAGNITUDE,
            MeasurementKind.MAXIMUM_WIND_SPEED,
            MeasurementKind.DEPTH,
            MeasurementKind.INTENSITY,
            MeasurementKind.SEVERITY,
        }:
            continue
        current = measurements_by_kind.get(measurement.kind)
        if current is not None and (
            current.source.source_id == packet.event.source.source_id
            or measurement.source.source_id != packet.event.source.source_id
        ):
            continue
        measurements_by_kind[measurement.kind] = measurement
    measurements = []
    for kind in (
        MeasurementKind.MAGNITUDE,
        MeasurementKind.MAXIMUM_WIND_SPEED,
        MeasurementKind.DEPTH,
        MeasurementKind.INTENSITY,
        MeasurementKind.SEVERITY,
    ):
        selected = measurements_by_kind.get(kind)
        if selected is None:
            continue
        label = _measurement_label(selected.kind, selected.source)
        value = f"{label} {selected.value}"
        if selected.unit:
            value += f" {selected.unit}"
        measurements.append(value)
        if len(measurements) == 3:
            break
    if measurements:
        parts.append("Reported measurements: " + "; ".join(measurements) + ".")
    ash_facts = [fact for fact in visible_facts if fact.category == "ash_observation"]
    if ash_facts:
        ash_fact = ash_facts[0]
        status = (
            ""
            if ash_fact.status is FactStatus.CONFIRMED
            else f" ({ash_fact.status.value})"
        )
        parts.append(f"Ash advisory: {ash_fact.value}{status}.")
    impact_categories = profile.human_categories | profile.physical_categories
    impact_facts = [
        fact for fact in visible_facts if fact.category in impact_categories
    ]
    if impact_facts:
        facts = []
        for fact in impact_facts[:2]:
            status = (
                "" if fact.status is FactStatus.CONFIRMED else f" ({fact.status.value})"
            )
            facts.append(f"{fact.label}: {fact.value}{status}")
        parts.append("Reported impacts: " + "; ".join(facts) + ".")
    else:
        parts.append(
            "The retrieved sources contain no event-specific human-impact or damage "
            "figures; this is not evidence of no impact."
        )
    return " ".join(parts)


def _event_summary(packet: EvidencePacket) -> str:
    event = packet.event
    country_name = packet.query.country.canonical_name
    event_location = " ".join(event.location.split())
    location = (
        event_location
        if country_name.lower() in event_location.lower()
        else f"{event_location}, {country_name}"
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
            omitted_count = sum(fact.category in categories for fact in omitted_facts)
            content = "\n".join(lines) if lines else missing
            if omitted_count:
                content += (
                    f"\n{omitted_count} other-area or country-wide reported "
                    "figures were omitted for the requested place."
                )
            return content

        narrative_lines = [f"- {narrative}" for narrative in packet.narratives]
        summary = _situation_summary(packet, visible_facts, profile)
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
