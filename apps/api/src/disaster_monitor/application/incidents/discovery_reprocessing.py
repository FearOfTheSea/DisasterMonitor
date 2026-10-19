"""Reassess retained source text without repeating news acquisition."""

from dataclasses import replace
from datetime import datetime
from hashlib import sha256

from disaster_monitor.domain.discovery import (
    DiscoveryRun,
    assess_article,
    group_reports,
    supplement_events,
)


def reprocess_retained_run(
    original: DiscoveryRun,
    *,
    scan_id: str,
    at: datetime,
    country_names: frozenset[str],
) -> DiscoveryRun:
    reports = tuple(
        assess_article(r.article, original.interval, country_names=country_names)
        for r in original.reports
    )
    events = supplement_events(group_reports(reports), original.supplemental)
    # Only reuse geography for unchanged source/place associations. New wording
    # cannot silently inherit a previous administrative boundary.
    geography = {
        (r.article.source.canonical_url, r.mention.place.wording): e.geometry
        for e in original.events
        if e.geometry is not None
        for r in e.reports
        if r.mention and r.mention.place
    }
    derived = []
    notice = (
        f"Reprocessed retained scan {original.scan_id}; no new news acquisition. "
        "Original acquisition limits remain."
    )
    for event in events:
        geometry = next(
            (
                geography.get((r.article.source.canonical_url, r.mention.place.wording))
                for r in event.reports
                if r.mention
                and r.mention.place
                and geography.get(
                    (r.article.source.canonical_url, r.mention.place.wording)
                )
            ),
            None,
        )
        derived.append(
            replace(
                event,
                # Source mention indexes can change after extraction updates. Scope
                # derived event IDs to this result so old selections remain immutable.
                event_id="discovery:"
                + sha256(f"{scan_id}|{event.event_id}".encode()).hexdigest()[:24],
                geometry=event.geometry or geometry,
                collection_notices=(*original.issues, notice),
            )
        )
    return replace(
        original,
        scan_id=scan_id,
        reports=reports,
        events=tuple(derived),
        reprocessed_from=original.scan_id,
        finished_at=at,
        issues=(*original.issues, notice),
    )
