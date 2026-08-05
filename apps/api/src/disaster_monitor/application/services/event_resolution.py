"""Explicit recent-event selection rules."""

from dataclasses import dataclass
from datetime import datetime, timedelta

from disaster_monitor.application.disaster import DisasterEvent, DisasterQuery


@dataclass(frozen=True, slots=True)
class EventResolution:
    """Selected event and any material ambiguity discovered during ranking."""

    selected: DisasterEvent | None
    alternatives: tuple[DisasterEvent, ...]
    ambiguous: bool
    rationale: str


def _score(event: DisasterEvent, now: datetime) -> float:
    age_hours = max(0.0, (now - event.event_time).total_seconds() / 3600)
    recency = max(0.0, 1.0 - age_hours / (30 * 24))
    magnitude = event.magnitude or 0.0
    significance = (event.significance or 0.0) / 1_000
    aftershock_penalty = 3.0 if event.is_aftershock else 0.0
    return recency * 2.0 + magnitude * 1.3 + significance - aftershock_penalty


def _same_sequence(first: DisasterEvent, second: DisasterEvent) -> bool:
    if first.parent_event_id and first.parent_event_id == second.event_id:
        return True
    if second.parent_event_id and second.parent_event_id == first.event_id:
        return True
    if first.is_aftershock != second.is_aftershock:
        return True
    if first.latitude is None or second.latitude is None:
        return False
    if first.longitude is None or second.longitude is None:
        return False
    distance = abs(first.latitude - second.latitude) + abs(
        first.longitude - second.longitude
    )
    return (
        distance <= 1.5
        and abs((first.event_time - second.event_time).total_seconds()) <= 48 * 3600
    )


def resolve_recent_event(
    candidates: tuple[DisasterEvent, ...],
    query: DisasterQuery,
    *,
    now: datetime,
) -> EventResolution:
    """Filter, rank, and detect ambiguity without model-driven routing."""
    window_start = now - timedelta(days=query.time_window_days)
    filtered = [
        event
        for event in candidates
        if event.hazard == query.hazard
        and event.country.lower() == query.geography.lower()
        and window_start <= event.event_time <= now + timedelta(minutes=5)
        and (
            query.event_identifier is None
            or query.event_identifier.lower() in event.event_id.lower()
        )
        and (query.magnitude is None or (event.magnitude or 0) >= query.magnitude - 0.1)
    ]
    if query.latitude is not None and query.longitude is not None:
        filtered = [
            event
            for event in filtered
            if event.latitude is None
            or (
                abs(event.latitude - query.latitude) <= 5
                and event.longitude is not None
                and abs(event.longitude - query.longitude) <= 5
            )
        ]
    ranked = sorted(filtered, key=lambda item: _score(item, now), reverse=True)
    if not ranked:
        return EventResolution(
            None, (), False, "No candidate matched the bounded query window."
        )

    selected = ranked[0]
    alternatives = tuple(ranked[1:4])
    ambiguous = False
    if len(ranked) > 1:
        second = ranked[1]
        score_gap = _score(selected, now) - _score(second, now)
        unrelated = not _same_sequence(selected, second)
        ambiguous = unrelated and score_gap < 0.6
    rationale = (
        "Selected the most significant recent candidate, accounting for recency and "
        "penalizing likely aftershocks."
    )
    if ambiguous:
        rationale = (
            "Multiple unrelated candidates have materially similar recency and "
            "significance."
        )
    return EventResolution(selected, alternatives, ambiguous, rationale)
