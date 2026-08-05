"""Explicit recent-event selection rules."""

import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from math import asin, cos, radians, sin, sqrt

from disaster_monitor.application.disaster import DisasterEvent, DisasterQuery


@dataclass(frozen=True, slots=True)
class EventResolution:
    """Selected event and any material ambiguity discovered during ranking."""

    selected: DisasterEvent | None
    alternatives: tuple[DisasterEvent, ...]
    ambiguous: bool
    rationale: str


def _distance_km(first: DisasterEvent, second: DisasterEvent) -> float | None:
    if None in (first.latitude, first.longitude, second.latitude, second.longitude):
        return None
    first_lat = radians(first.latitude or 0)
    second_lat = radians(second.latitude or 0)
    delta_lat = radians((second.latitude or 0) - (first.latitude or 0))
    delta_lon = radians((second.longitude or 0) - (first.longitude or 0))
    value = (
        sin(delta_lat / 2) ** 2
        + cos(first_lat) * cos(second_lat) * sin(delta_lon / 2) ** 2
    )
    return 6371 * 2 * asin(sqrt(value))


def _location_matches(event: DisasterEvent, value: str) -> bool:
    wanted = re.sub(r"[^a-z0-9]+", " ", value.lower()).split()
    actual = re.sub(r"[^a-z0-9]+", " ", event.location.lower()).split()
    return bool(wanted) and all(token in actual for token in wanted)


def _score(event: DisasterEvent, query: DisasterQuery, now: datetime) -> float:
    age_hours = max(0.0, (now - event.event_time).total_seconds() / 3600)
    recency = max(0.0, 1.0 - age_hours / (30 * 24))
    magnitude = event.magnitude or 0.0
    significance = (event.significance or 0.0) / 500
    intensity = _intensity_score(event.intensity)
    aftershock_penalty = 3.0 if event.is_aftershock else 0.0
    discriminator_bonus = 0.0
    if query.prefecture and _location_matches(event, query.prefecture):
        discriminator_bonus += 8.0
    if query.city and _location_matches(event, query.city):
        discriminator_bonus += 8.0
    if query.latitude is not None and query.longitude is not None:
        distance = _distance_to_coordinates(event, query.latitude, query.longitude)
        if distance is not None:
            discriminator_bonus += max(0.0, 8.0 - distance / 25.0)
    if query.magnitude is not None and event.magnitude is not None:
        discriminator_bonus += max(
            0.0, 4.0 - abs(event.magnitude - query.magnitude) * 8
        )
    return (
        recency * 0.6
        + magnitude * 2.0
        + intensity * 1.5
        + significance
        + discriminator_bonus
        - aftershock_penalty
    )


def _intensity_score(value: str | None) -> float:
    if not value:
        return 0.0
    normalized = (
        value.lower()
        .replace("jma", "")
        .translate(str.maketrans("０１２３４５６７", "01234567"))
        .strip()
    )
    for token, score in (
        ("7", 7.0),
        ("6+", 6.0),
        ("6-", 5.5),
        ("5+", 5.0),
        ("5-", 4.5),
        ("4", 4.0),
        ("3", 3.0),
        ("2", 2.0),
        ("1", 1.0),
    ):
        if token in normalized:
            return score
    return 0.0


def _distance_to_coordinates(
    event: DisasterEvent, latitude: float, longitude: float
) -> float | None:
    if event.latitude is None or event.longitude is None:
        return None
    first_lat = radians(event.latitude)
    second_lat = radians(latitude)
    delta_lat = radians(latitude - event.latitude)
    delta_lon = radians(longitude - event.longitude)
    value = (
        sin(delta_lat / 2) ** 2
        + cos(first_lat) * cos(second_lat) * sin(delta_lon / 2) ** 2
    )
    return 6371 * 2 * asin(sqrt(value))


def _same_sequence(first: DisasterEvent, second: DisasterEvent) -> bool:
    first_ids = {first.event_id, *first.provider_ids}
    second_ids = {second.event_id, *second.provider_ids}
    if first.parent_event_id and first.parent_event_id in second_ids:
        return True
    if second.parent_event_id and second.parent_event_id in first_ids:
        return True
    if first.sequence_id and first.sequence_id == second.sequence_id:
        return True
    if not (first.is_aftershock or second.is_aftershock):
        return False
    distance = _distance_km(first, second)
    if distance is None:
        return False
    return (
        distance <= 50
        and abs((first.event_time - second.event_time).total_seconds()) <= 48 * 3600
    )


def resolve_recent_event(
    candidates: tuple[DisasterEvent, ...],
    query: DisasterQuery,
    *,
    now: datetime,
) -> EventResolution:
    """Filter, rank, and detect ambiguity without model-driven routing."""
    window_start = query.date_from or now - timedelta(days=query.time_window_days)
    window_end = query.date_to or now + timedelta(minutes=5)
    filtered = [
        event
        for event in candidates
        if event.hazard == query.hazard
        and event.country.lower() == query.geography.lower()
        and window_start <= event.event_time <= window_end
        and (
            query.event_identifier is None
            or event.has_provider_id(query.event_identifier)
        )
        and (
            query.magnitude is None
            or (
                event.magnitude is not None
                and abs(event.magnitude - query.magnitude) <= 0.25
            )
        )
    ]
    if query.prefecture:
        filtered = [
            event for event in filtered if _location_matches(event, query.prefecture)
        ]
    if query.city:
        filtered = [event for event in filtered if _location_matches(event, query.city)]
    if query.latitude is not None and query.longitude is not None:
        distances = [
            (event, _distance_to_coordinates(event, query.latitude, query.longitude))
            for event in filtered
        ]
        filtered = [
            event
            for event, distance in distances
            if distance is not None and distance <= 150
        ]
    ranked = sorted(filtered, key=lambda item: _score(item, query, now), reverse=True)
    if not ranked:
        return EventResolution(
            None, (), False, "No candidate matched the bounded query window."
        )

    selected = ranked[0]
    alternatives = tuple(ranked[1:4])
    ambiguous = False
    if len(ranked) > 1:
        second = ranked[1]
        score_gap = _score(selected, query, now) - _score(second, query, now)
        unrelated = not _same_sequence(selected, second)
        ambiguous = unrelated and (score_gap < 0.6 or second.is_aftershock)
    rationale = (
        "Selected the highest-ranked recent candidate using maximum JMA intensity, "
        "magnitude, provider significance, recency, and an aftershock penalty; "
        "magnitude and intensity outweigh a small age difference."
    )
    if any(
        (
            query.event_identifier,
            query.date_from,
            query.date_to,
            query.prefecture,
            query.city,
            query.latitude is not None and query.longitude is not None,
            query.magnitude is not None,
        )
    ):
        rationale = (
            "Selected the candidate matching the explicit date, location, coordinate, "
            "magnitude, or event-identifier discriminator."
        )
    if ambiguous:
        rationale = (
            "Multiple unrelated candidates have materially similar recency and "
            "significance."
        )
    return EventResolution(selected, alternatives, ambiguous, rationale)
