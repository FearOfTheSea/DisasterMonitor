"""Bounded place enrichment; geography never participates in article admission."""

import re
from dataclasses import replace

from disaster_monitor.application.ports.mention_geography import (
    MentionPlaceResolver,
    PlaceResolution,
)
from disaster_monitor.domain.discovery import DiscoveryEvent


async def resolve_event_places(
    events: tuple[DiscoveryEvent, ...],
    resolver: MentionPlaceResolver,
    *,
    maximum: int = 4,
) -> tuple[DiscoveryEvent, ...]:
    results: dict[tuple[str, str | None], PlaceResolution] = {}
    enriched: dict[str, DiscoveryEvent] = {}
    # Spend the existing budget on usable occurred-event targets first.
    prioritized = sorted(
        events,
        key=lambda event: (
            not any(
                r.mention and r.mention.role in ("reported", "ongoing")
                for r in event.reports
            ),
            event.event_time is None,
            event.identity_status != "associated",
        ),
    )
    for event in prioritized:
        candidates = [
            r
            for r in event.reports
            if r.mention
            and r.mention.role in ("reported", "ongoing")
            and r.mention.place
            and r.mention.place.precision == "named_place"
        ]
        if event.geometry is not None or not candidates:
            enriched[event.event_id] = event
            continue
        report = candidates[0]
        assert report.mention and report.mention.place
        place = report.mention.place.wording
        # A conjunction names several source places, not a single provider name.
        # One resolved component is explicitly partial administrative context.
        components = re.split(r"\s+(?:&|and)\s+", place)
        resolution = None
        resolved_place = place
        for component in components:
            key = (component, report.mention.country_context)
            if key not in results and len(results) < maximum:
                try:
                    results[key] = await resolver.resolve(*key)
                except Exception:
                    results[key] = PlaceResolution(
                        "unavailable",
                        detail="Place resolver failed; source wording retained.",
                    )
            resolution = results.get(key)
            if resolution and resolution.status == "resolved":
                resolved_place = component
                break
        if resolution and resolution.status == "resolved" and resolution.geometry:
            geometry = resolution.geometry
            if len(components) > 1:
                geometry = replace(
                    geometry,
                    description=(
                        f"Only {resolved_place} within reported '{place}' is mapped. "
                        "Partial administrative inspection context; "
                        "not the full affected area. "
                        f"{geometry.description or ''}"
                    ),
                )
            event = replace(
                event,
                geometry=geometry,
                reports=tuple(
                    replace(
                        r,
                        mention=replace(
                            r.mention,
                            geometry=geometry,
                            notices=(*r.mention.notices, resolution.detail),
                        ),
                    )
                    if r.mention and r.mention.place == report.mention.place
                    else r
                    for r in event.reports
                ),
                supplemental_sources=(*event.supplemental_sources, geometry.source),
            )
        notice = (
            resolution.detail
            if resolution
            else "Place-resolution budget reached; source wording retained."
        )
        enriched[event.event_id] = replace(
            event, collection_notices=(*event.collection_notices, notice)
        )
    return tuple(enriched[event.event_id] for event in events)
