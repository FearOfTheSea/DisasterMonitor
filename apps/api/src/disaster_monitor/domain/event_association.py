"""Explainable association of physical mentions, with ambiguity retained."""

import hashlib
from dataclasses import replace
from typing import Literal

from disaster_monitor.domain.discovery import AssessedReport, DiscoveryEvent
from disaster_monitor.domain.event_identifiers import (
    EventIdentifierRole,
    event_identifier_role,
)
from disaster_monitor.domain.events import EventGeometryKind, geographic_distance_km
from disaster_monitor.domain.mention_extraction import extract_mentions
from disaster_monitor.domain.mention_occurrence import same_occurrence_detail


def _compatible(first: AssessedReport, other: AssessedReport) -> bool:
    a, b = first.mention, other.mention
    assert a and b
    if a.disaster != b.disaster or a.role != b.role:
        return False
    if (
        first.article.location
        and other.article.location
        and first.article.location.casefold() != other.article.location.casefold()
    ):
        return False
    if (
        first.article.event_key
        and other.article.event_key
        and first.article.event_key != other.article.event_key
    ):
        return False
    if a.name and b.name and a.name.casefold() != b.name.casefold():
        return False
    if (
        a.distinguishing_evidence
        and b.distinguishing_evidence
        and a.distinguishing_evidence.casefold() != b.distinguishing_evidence.casefold()
    ):
        import re

        if not same_occurrence_detail(
            a.distinguishing_evidence, b.distinguishing_evidence
        ) and not re.search(
            r"\b(?:revised|corrected|revision)\b", a.text + " " + b.text, re.I
        ):
            return False
    if a.time and b.time and a.time.start and b.time.start:
        end_a, end_b = a.time.end or a.time.start, b.time.end or b.time.start
        if end_a < b.time.start or end_b < a.time.start:
            return False
        # Adjacent day ranges are different event days.
        if (
            end_a == b.time.start or end_b == a.time.start
        ) and a.time.start != b.time.start:
            return False
    return True


def _reason(first: AssessedReport, other: AssessedReport) -> str | None:
    a, b = first.mention, other.mention
    assert a and b
    if not _compatible(first, other):
        return None
    if (
        first.article.source.canonical_url == other.article.source.canonical_url
        and (a.occurrence_anchor_id or b.occurrence_anchor_id)
        and (a.occurrence_anchor_id or a.mention_id)
        == (b.occurrence_anchor_id or b.mention_id)
    ):
        return (
            "Same article explicitly links these accounts to one physical "
            "occurrence; impact accounts retain their reported geographic scope."
        )
    # A broad sequence or origin shared by multiple mentions is not an event key.
    single = (
        (first.mention_count or len(first.mentions))
        == (other.mention_count or len(other.mentions))
        == 1
    )
    if (
        single
        and first.article.event_key
        and event_identifier_role(first.article.event_key)
        is EventIdentifierRole.PHYSICAL_EVENT
        and first.article.event_key == other.article.event_key
    ):
        return "Same explicit source event identifier; compatible hazard/time."
    if single and first.article.origin and first.article.origin == other.article.origin:
        return (
            "Same explicit reporting origin; "
            "republication is not independent confirmation."
        )
    if not (a.time and b.time and a.time.start and b.time.start):
        return None
    # Approximate periods cannot by themselves distinguish nearby occurrences.
    if a.time.precision not in ("day", "exact") or b.time.precision not in (
        "day",
        "exact",
    ):
        return None
    if (
        a.name
        and b.name
        and a.name.casefold() == b.name.casefold()
        and a.time.start.year == b.time.start.year
    ):
        return "Same named hazard and compatible reported event period."
    if (
        a.place
        and b.place
        and a.place.precision == b.place.precision == "named_place"
        and a.place.wording.casefold() == b.place.wording.casefold()
    ):
        if (
            a.time.precision == b.time.precision == "exact"
            and abs((a.time.start - b.time.start).total_seconds()) > 3600
        ):
            return None
        return "Same specific named place, hazard and compatible reported event day."
    if (
        a.geometry
        and b.geometry
        and a.geometry.kind == b.geometry.kind == EventGeometryKind.POINT
        and a.time.precision == b.time.precision == "exact"
        and abs((a.time.start - b.time.start).total_seconds()) <= 60
        and geographic_distance_km(a.geometry.coordinates[0], b.geometry.coordinates[0])
        <= 5
    ):
        return "Compatible source points within 5 km and exact onset within one minute."
    return None


def associate_mentions(
    reports: tuple[AssessedReport, ...], previous: tuple[DiscoveryEvent, ...]
) -> tuple[DiscoveryEvent, ...]:
    groups: list[list[AssessedReport]] = []
    reasons: list[list[str]] = []
    deferred: list[AssessedReport] = []
    seen = set()
    for report in reports:
        if report.eligibility in ("outside_interval", "unclassified"):
            continue
        mentions = report.mentions or extract_mentions(
            report.article.text,
            report.article.source,
            location=report.article.location,
            event_time=report.article.event_time,
            geometry=report.article.geometry,
        )
        for mention in mentions:
            if mention.mention_id in seen:
                continue
            seen.add(mention.mention_id)
            projected = replace(
                report,
                disaster=mention.disaster,
                mention=mention,
                mentions=(),
                mention_count=len(
                    {
                        m.occurrence_anchor_id or m.mention_id
                        for m in mentions
                        if m.role in ("reported", "ongoing")
                    }
                ),
            )
            if report.eligibility == "unknown_publication":
                deferred.append(projected)
                continue
            _place_report(projected, groups, reasons)
    for report in deferred:
        matches = [
            i
            for i, group in enumerate(groups)
            if all(_compatible(r, report) for r in group)
            and any(_reason(r, report) for r in group)
        ]
        if len(matches) == 1:
            groups[matches[0]].append(report)
            reasons[matches[0]].append(
                "Undated account supplements an eligible event; "
                "does not establish window eligibility."
            )
    result = []
    used_ids: set[str] = set()
    for group, why in zip(groups, reasons, strict=True):
        first = group[0]
        first_mention = first.mention
        assert first_mention is not None
        mention = first_mention
        anchors = {
            r.mention.occurrence_anchor_id
            for r in group
            if r.mention and r.mention.occurrence_anchor_id
        }
        identity_anchor = next(
            (r.mention for r in group if r.mention and r.mention.mention_id in anchors),
            None,
        )
        located = next(
            (r.mention for r in group if r.mention and r.mention.geometry), mention
        )
        if identity_anchor is not None:
            located = identity_anchor
        timed = next(
            (
                r.mention
                for r in group
                if r.mention and r.mention.time and r.mention.time.start
            ),
            mention,
        )
        ids = {r.mention.mention_id for r in group if r.mention}
        retained_id = next(
            (
                e.event_id
                for e in previous
                if e.event_id not in used_ids
                and any(r.mention and r.mention.mention_id in ids for r in e.reports)
            ),
            None,
        )
        event_id = (
            retained_id
            or "discovery:"
            + hashlib.sha256(mention.mention_id.encode()).hexdigest()[:24]
        )
        used_ids.add(event_id)
        known = (
            len(group) > 1
            or (
                first.article.event_key
                and event_identifier_role(first.article.event_key)
                is EventIdentifierRole.PHYSICAL_EVENT
            )
            or (
                located.place
                and located.place.precision == "named_place"
                and timed.time
                and timed.time.start
            )
        )
        ambiguous = any(reason.startswith("Ambiguous association") for reason in why)
        status: Literal["candidate", "associated"] = (
            "associated"
            if known
            and not ambiguous
            and any(r.eligibility == "eligible" for r in group)
            and mention.role in ("reported", "ongoing")
            else "candidate"
        )
        result.append(
            DiscoveryEvent(
                event_id=event_id,
                disaster=mention.disaster,
                location=next(
                    (
                        r.mention.place.wording
                        for r in group
                        if r.mention
                        and r.mention.occurrence_anchor_id
                        and r.mention.place
                        and r.mention.place.precision == "country_context"
                    ),
                    located.place.wording
                    if located.place
                    else first.article.location or first.article.source.title,
                ),
                event_time=timed.time.start if timed.time else None,
                geometry=located.geometry,
                reports=tuple(group),
                independent_origins=len(
                    {r.article.origin for r in group if r.article.origin}
                ),
                identity_status=status,
                association_reasons=tuple(dict.fromkeys(why))
                or (
                    "No unique cross-report association established; "
                    "retained source mention.",
                ),
            )
        )
    return tuple(result)


def _place_report(
    report: AssessedReport, groups: list[list[AssessedReport]], reasons: list[list[str]]
) -> None:
    matches = []
    for index, group in enumerate(groups):
        why = next((_reason(r, report) for r in group if _reason(r, report)), None)
        if why and all(_compatible(r, report) for r in group):
            matches.append((index, why))
    if len(matches) == 1:
        index, why = matches[0]
        groups[index].append(report)
        reasons[index].append(why)
    else:
        groups.append([report])
        reasons.append(
            [
                "Ambiguous association to multiple existing events; "
                "candidate retained separately."
            ]
            if matches
            else []
        )
