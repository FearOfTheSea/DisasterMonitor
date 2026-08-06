"""Hazard-specific event equivalence, ranking, and ambiguity policies."""

import re
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from math import asin, cos, radians, sin, sqrt
from typing import Protocol

from disaster_monitor.application.disaster import DisasterQuery
from disaster_monitor.domain.disaster import DisasterEvent, Hazard


@dataclass(frozen=True, slots=True)
class EventResolution:
    """Selected event and any material ambiguity discovered during ranking."""

    selected: DisasterEvent | None
    alternatives: tuple[DisasterEvent, ...]
    ambiguous: bool
    rationale: str


class EventPolicy(Protocol):
    """Hazard policy for real-world equivalence and event selection."""

    ambiguity_threshold: float

    def rank(
        self, event: DisasterEvent, query: DisasterQuery, now: datetime
    ) -> float: ...

    def same_physical_event(
        self, first: DisasterEvent, second: DisasterEvent
    ) -> bool: ...

    def same_sequence(self, first: DisasterEvent, second: DisasterEvent) -> bool: ...

    def describe_selection(self, query: DisasterQuery, ambiguous: bool) -> str: ...

    def cluster(
        self, events: tuple[DisasterEvent, ...]
    ) -> tuple[DisasterEvent, ...]: ...

    def resolve(
        self,
        candidates: tuple[DisasterEvent, ...],
        query: DisasterQuery,
        *,
        now: datetime,
    ) -> EventResolution: ...


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


def _distance_to_coordinates(
    event: DisasterEvent, latitude: float, longitude: float
) -> float | None:
    if event.latitude is None or event.longitude is None:
        return None
    target = replace(event, latitude=latitude, longitude=longitude)
    return _distance_km(event, target)


def _location_matches(event: DisasterEvent, value: str) -> bool:
    wanted = re.sub(r"[^a-z0-9]+", " ", value.lower()).split()
    actual = re.sub(r"[^a-z0-9]+", " ", event.location.lower()).split()
    return bool(wanted) and all(token in actual for token in wanted)


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


def _provider_identifiers(event: DisasterEvent) -> set[str]:
    return {event.event_id.lower(), *(item.lower() for item in event.provider_ids)}


def _preferred_event(events: list[DisasterEvent]) -> DisasterEvent:
    return max(
        events,
        key=lambda event: (
            event.magnitude is not None,
            event.latitude is not None and event.longitude is not None,
            event.significance or 0,
            "usgs:" in event.event_id.lower(),
        ),
    )


def _merge_event(events: list[DisasterEvent]) -> DisasterEvent:
    if len(events) == 1:
        return events[0]
    preferred = _preferred_event(events)
    richest = max(
        events,
        key=lambda event: (
            event.intensity is not None,
            event.depth_km is not None,
            event.latitude is not None and event.longitude is not None,
        ),
    )
    return replace(
        preferred,
        intensity=preferred.intensity or richest.intensity,
        depth_km=preferred.depth_km
        if preferred.depth_km is not None
        else richest.depth_km,
        significance=max((event.significance or 0) for event in events),
        is_aftershock=any(event.is_aftershock for event in events),
        parent_event_id=preferred.parent_event_id or richest.parent_event_id,
        sequence_id=preferred.sequence_id or richest.sequence_id,
        provider_ids=tuple(
            dict.fromkeys(
                identifier
                for event in events
                for identifier in (event.event_id, *event.provider_ids)
            )
        ),
    )


class BaseEventPolicy:
    """Shared conservative filtering and clustering mechanics."""

    ambiguity_threshold = 0.6

    def rank(self, event: DisasterEvent, query: DisasterQuery, now: datetime) -> float:
        raise NotImplementedError

    def describe_selection(self, query: DisasterQuery, ambiguous: bool) -> str:
        raise NotImplementedError

    def same_physical_event(self, first: DisasterEvent, second: DisasterEvent) -> bool:
        return bool(_provider_identifiers(first) & _provider_identifiers(second))

    def same_sequence(self, first: DisasterEvent, second: DisasterEvent) -> bool:
        return self.same_physical_event(first, second)

    def cluster(self, events: tuple[DisasterEvent, ...]) -> tuple[DisasterEvent, ...]:
        clusters: list[list[DisasterEvent]] = []
        for event in events:
            for cluster in clusters:
                if any(self.same_physical_event(event, item) for item in cluster):
                    cluster.append(event)
                    break
            else:
                clusters.append([event])
        return tuple(_merge_event(cluster) for cluster in clusters)

    def _filtered(
        self,
        candidates: tuple[DisasterEvent, ...],
        query: DisasterQuery,
        now: datetime,
    ) -> list[DisasterEvent]:
        window_start = query.date_from or now - timedelta(days=query.time_window_days)
        window_end = query.date_to or now + timedelta(minutes=5)
        filtered = [
            event
            for event in candidates
            if event.hazard == query.hazard
            and event.country.alpha3_code == query.country.alpha3_code
            and window_start <= event.event_time <= window_end
            and (
                query.event_identifier is None
                or event.has_provider_id(query.event_identifier)
            )
        ]
        if query.prefecture:
            filtered = [
                event
                for event in filtered
                if _location_matches(event, query.prefecture)
            ]
        if query.city:
            filtered = [
                event for event in filtered if _location_matches(event, query.city)
            ]
        if query.latitude is not None and query.longitude is not None:
            filtered = [
                event
                for event in filtered
                if (
                    distance := _distance_to_coordinates(
                        event, query.latitude, query.longitude
                    )
                )
                is not None
                and distance <= 150
            ]
        return filtered

    def resolve(
        self,
        candidates: tuple[DisasterEvent, ...],
        query: DisasterQuery,
        *,
        now: datetime,
    ) -> EventResolution:
        ranked = sorted(
            self._filtered(candidates, query, now),
            key=lambda item: self.rank(item, query, now),
            reverse=True,
        )
        if not ranked:
            return EventResolution(
                None, (), False, "No candidate matched the bounded query window."
            )
        selected = ranked[0]
        alternatives = tuple(ranked[1:4])
        ambiguous = False
        if len(ranked) > 1:
            second = ranked[1]
            score_gap = self.rank(selected, query, now) - self.rank(second, query, now)
            ambiguous = (
                not self.same_sequence(selected, second)
                and score_gap < self.ambiguity_threshold
            )
        return EventResolution(
            selected,
            alternatives,
            ambiguous,
            self.describe_selection(query, ambiguous),
        )


class EarthquakeEventPolicy(BaseEventPolicy):
    """Earthquake mainshock, equivalence, ranking, and ambiguity policy."""

    def rank(self, event: DisasterEvent, query: DisasterQuery, now: datetime) -> float:
        age_hours = max(0.0, (now - event.event_time).total_seconds() / 3600)
        recency = max(0.0, 1.0 - age_hours / (30 * 24))
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
            + (event.magnitude or 0.0) * 2.0
            + _intensity_score(event.intensity) * 1.5
            + (event.significance or 0.0) / 500
            + discriminator_bonus
            - (3.0 if event.is_aftershock else 0.0)
        )

    def same_physical_event(self, first: DisasterEvent, second: DisasterEvent) -> bool:
        if first.hazard != second.hazard or first.country != second.country:
            return False
        if super().same_physical_event(first, second):
            return True
        if abs((first.event_time - second.event_time).total_seconds()) > 90:
            return False
        distance = _distance_km(first, second)
        if distance is None or distance > 30:
            return False
        return not (
            first.magnitude is not None
            and second.magnitude is not None
            and abs(first.magnitude - second.magnitude) > 0.5
        )

    def same_sequence(self, first: DisasterEvent, second: DisasterEvent) -> bool:
        first_ids = _provider_identifiers(first)
        second_ids = _provider_identifiers(second)
        if first.parent_event_id and first.parent_event_id.lower() in second_ids:
            return True
        if second.parent_event_id and second.parent_event_id.lower() in first_ids:
            return True
        if first.sequence_id and first.sequence_id == second.sequence_id:
            return True
        if not (first.is_aftershock or second.is_aftershock):
            return False
        distance = _distance_km(first, second)
        return bool(
            distance is not None
            and distance <= 50
            and abs((first.event_time - second.event_time).total_seconds()) <= 48 * 3600
        )

    def _filtered(
        self,
        candidates: tuple[DisasterEvent, ...],
        query: DisasterQuery,
        now: datetime,
    ) -> list[DisasterEvent]:
        filtered = super()._filtered(candidates, query, now)
        if query.magnitude is not None:
            filtered = [
                event
                for event in filtered
                if event.magnitude is not None
                and abs(event.magnitude - query.magnitude) <= 0.25
            ]
        return filtered

    def describe_selection(self, query: DisasterQuery, ambiguous: bool) -> str:
        if ambiguous:
            return (
                "Multiple unrelated earthquake candidates have materially similar "
                "recency and significance."
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
            return (
                "Selected the earthquake matching the explicit date, location, "
                "coordinate, magnitude, or event-identifier discriminator."
            )
        return (
            "Selected the highest-ranked recent earthquake using intensity, "
            "magnitude, provider significance, recency, and an aftershock penalty."
        )

    def resolve(
        self,
        candidates: tuple[DisasterEvent, ...],
        query: DisasterQuery,
        *,
        now: datetime,
    ) -> EventResolution:
        resolution = super().resolve(candidates, query, now=now)
        if resolution.selected is None or not resolution.alternatives:
            return resolution
        second = resolution.alternatives[0]
        ambiguous = not self.same_sequence(resolution.selected, second) and (
            self.rank(resolution.selected, query, now) - self.rank(second, query, now)
            < self.ambiguity_threshold
            or second.is_aftershock
        )
        return replace(
            resolution,
            ambiguous=ambiguous,
            rationale=self.describe_selection(query, ambiguous),
        )


class DefaultEventPolicy(BaseEventPolicy):
    """Conservative policy for hazards without dedicated equivalence rules."""

    ambiguity_threshold = 6.0 * 3600

    def rank(self, event: DisasterEvent, query: DisasterQuery, now: datetime) -> float:
        return event.event_time.timestamp()

    def describe_selection(self, query: DisasterQuery, ambiguous: bool) -> str:
        if ambiguous:
            return (
                f"Multiple independent {query.hazard.value} events have similarly "
                "recent source timestamps."
            )
        return "Selected the newest matching source-backed event."

    def resolve(
        self,
        candidates: tuple[DisasterEvent, ...],
        query: DisasterQuery,
        *,
        now: datetime,
    ) -> EventResolution:
        resolution = super().resolve(candidates, query, now=now)
        if resolution.selected is None or not resolution.alternatives:
            return resolution
        second = resolution.alternatives[0]
        similar = abs(
            (resolution.selected.event_time - second.event_time).total_seconds()
        ) < self.ambiguity_threshold and not self.same_sequence(
            resolution.selected, second
        )
        return replace(
            resolution,
            ambiguous=similar,
            rationale=self.describe_selection(query, similar),
        )


class EventPolicyRegistry:
    """Resolve a typed hazard to a dedicated or conservative event policy."""

    def __init__(
        self, policies: dict[Hazard, EventPolicy], default: EventPolicy
    ) -> None:
        self._policies = dict(policies)
        self._default = default

    def for_hazard(self, hazard: Hazard) -> EventPolicy:
        return self._policies.get(hazard, self._default)


def default_event_policy_registry() -> EventPolicyRegistry:
    return EventPolicyRegistry(
        {Hazard.EARTHQUAKE: EarthquakeEventPolicy()}, DefaultEventPolicy()
    )


def resolve_recent_event(
    candidates: tuple[DisasterEvent, ...],
    query: DisasterQuery,
    *,
    now: datetime,
) -> EventResolution:
    """Compatibility entry point backed by the typed hazard policy registry."""
    policy = default_event_policy_registry().for_hazard(query.hazard)
    return policy.resolve(policy.cluster(candidates), query, now=now)


def cluster_physical_events(
    events: tuple[DisasterEvent, ...], hazard: Hazard = Hazard.EARTHQUAKE
) -> tuple[DisasterEvent, ...]:
    """Cluster equivalent records using application-owned hazard policy."""
    return default_event_policy_registry().for_hazard(hazard).cluster(events)
