"""Hazard-specific event equivalence, ranking, and ambiguity policies."""

import re
from collections import deque
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from math import asin, cos, radians, sin, sqrt
from typing import Protocol

from disaster_monitor.application.disaster import DisasterQuery
from disaster_monitor.domain.disaster import (
    DisasterEvent,
    EarthquakeEvent,
    EventAssignmentStatus,
    EventCoordinate,
    EventGeometryKind,
    EventObservationAssignment,
    Hazard,
    MeasurementKind,
    PhysicalEventIdentity,
    PhysicalEventIdentityResult,
)


@dataclass(frozen=True, slots=True)
class EventResolution:
    """Selected event and any material ambiguity discovered during ranking."""

    selected: DisasterEvent | None
    alternatives: tuple[DisasterEvent, ...]
    ambiguous: bool
    rationale: str
    physical_events: tuple[PhysicalEventIdentity, ...] = ()
    selected_physical_event: PhysicalEventIdentity | None = None
    ambiguous_assignments: tuple[EventObservationAssignment, ...] = ()


class EventPolicy(Protocol):
    """Hazard policy for real-world equivalence and event selection."""

    ambiguity_threshold: float

    def rank(
        self, event: DisasterEvent, query: DisasterQuery, now: datetime
    ) -> float: ...

    def same_physical_event(
        self, first: DisasterEvent, second: DisasterEvent
    ) -> bool: ...

    def describe_selection(self, query: DisasterQuery, ambiguous: bool) -> str: ...

    def cluster(
        self, events: tuple[DisasterEvent, ...]
    ) -> tuple[DisasterEvent, ...]: ...

    def identify(
        self, events: tuple[DisasterEvent, ...]
    ) -> PhysicalEventIdentityResult: ...

    def resolve(
        self,
        candidates: tuple[DisasterEvent, ...],
        query: DisasterQuery,
        *,
        now: datetime,
    ) -> EventResolution: ...


def _distance_km(first: DisasterEvent, second: DisasterEvent) -> float | None:
    first_point = _event_point(first)
    second_point = _event_point(second)
    if first_point is None or second_point is None:
        return None
    first_lat = radians(first_point.latitude)
    second_lat = radians(second_point.latitude)
    delta_lat = radians(second_point.latitude - first_point.latitude)
    delta_lon = radians(second_point.longitude - first_point.longitude)
    value = (
        sin(delta_lat / 2) ** 2
        + cos(first_lat) * cos(second_lat) * sin(delta_lon / 2) ** 2
    )
    return 6371 * 2 * asin(sqrt(value))


def _distance_to_coordinates(
    event: DisasterEvent, latitude: float, longitude: float
) -> float | None:
    point = _event_point(event)
    if point is None:
        return None
    geometry = event.geometry
    if geometry is None:
        return None
    target = replace(
        event,
        geometry=replace(
            geometry,
            coordinates=(replace(point, latitude=latitude, longitude=longitude),),
        ),
    )
    return _distance_km(event, target)


def _event_point(event: DisasterEvent) -> EventCoordinate | None:
    geometry = event.geometry
    if geometry is None or geometry.kind is not EventGeometryKind.POINT:
        return None
    return geometry.coordinates[0]


def _measurement(event: DisasterEvent, kind: MeasurementKind) -> float | str | None:
    measurement = event.measurement(kind)
    return measurement.value if measurement is not None else None


def _is_aftershock(event: DisasterEvent) -> bool:
    return isinstance(event, EarthquakeEvent) and event.is_aftershock


def _location_matches(event: DisasterEvent, value: str) -> bool:
    wanted = re.sub(r"[^a-z0-9]+", " ", value.lower()).split()
    actual = re.sub(r"[^a-z0-9]+", " ", event.location.lower()).split()
    return bool(wanted) and all(token in actual for token in wanted)


def _intensity_score(value: float | str | None) -> float:
    if not value:
        return 0.0
    if not isinstance(value, str):
        return float(value)
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


def _qualified_identifier(event: DisasterEvent, identifier: str) -> str:
    normalized = identifier.strip().lower()
    if ":" in normalized:
        return normalized
    return f"{event.source.source_id.lower()}:{normalized}"


def _provider_identifiers(event: DisasterEvent) -> set[str]:
    return {
        _qualified_identifier(event, item)
        for item in (event.event_id, *event.provider_ids)
        if item.strip()
    }


def event_observation_key(event: DisasterEvent) -> str:
    """Return a stable key for one normalized provider observation."""
    timestamp = event.event_time.astimezone(UTC).isoformat()
    material = "|".join(
        (
            event.source.source_id.lower(),
            event.event_id.lower(),
            event.hazard.value,
            event.country.alpha3_code.lower(),
            timestamp,
            event.location.casefold(),
            str(event.geometry),
            event.source.canonical_url.lower(),
        )
    )
    digest = sha256(material.encode("utf-8")).hexdigest()[:16]
    return f"observation:{event.source.source_id.lower()}:{digest}"


def _event_order_key(event: DisasterEvent) -> tuple[str, str, str, str]:
    return (
        event.hazard.value,
        event.country.alpha3_code,
        event.event_time.astimezone(UTC).isoformat(),
        event_observation_key(event),
    )


def _preferred_event(events: list[DisasterEvent]) -> DisasterEvent:
    return max(
        events,
        key=lambda event: (
            event.source.effective_at,
            event_observation_key(event),
        ),
    )


def _merge_event(events: list[DisasterEvent]) -> DisasterEvent:
    events = sorted(events, key=_event_order_key)
    if len(events) == 1:
        return events[0]
    preferred = _preferred_event(events)
    measurements = tuple(
        sorted(
            set(measurement for event in events for measurement in event.measurements),
            key=lambda item: (
                item.kind.value,
                item.unit or "",
                str(item.value),
                item.source.source_id,
                item.source.canonical_url,
            ),
        )
    )
    geometry = preferred.geometry or next(
        (event.geometry for event in events if event.geometry is not None), None
    )
    return replace(
        preferred,
        geometry=geometry,
        measurements=measurements,
        provider_ids=tuple(
            sorted(
                set(
                    identifier
                    for event in events
                    for identifier in (event.event_id, *event.provider_ids)
                )
            )
        ),
    )


def _physical_event_id(events: tuple[DisasterEvent, ...]) -> str:
    first = events[0]
    material = "|".join(event_observation_key(event) for event in events)
    digest = sha256(material.encode("utf-8")).hexdigest()[:20]
    return (
        f"physical-event:{first.hazard.value}:"
        f"{first.country.alpha3_code.lower()}:{digest}"
    )


class BaseEventPolicy:
    """Shared conservative filtering and clustering mechanics."""

    ambiguity_threshold = 0.6

    def rank(self, event: DisasterEvent, query: DisasterQuery, now: datetime) -> float:
        raise NotImplementedError

    def describe_selection(self, query: DisasterQuery, ambiguous: bool) -> str:
        raise NotImplementedError

    def _merge_event(self, events: list[DisasterEvent]) -> DisasterEvent:
        return _merge_event(events)

    def same_physical_event(self, first: DisasterEvent, second: DisasterEvent) -> bool:
        if (
            first.hazard != second.hazard
            or first.country.alpha3_code != second.country.alpha3_code
        ):
            return False
        shared_identifiers = _provider_identifiers(first) & _provider_identifiers(
            second
        )
        return bool(
            shared_identifiers
            and abs((first.event_time - second.event_time).total_seconds()) <= 24 * 3600
        )

    def cluster(self, events: tuple[DisasterEvent, ...]) -> tuple[DisasterEvent, ...]:
        """Compatibility projection of the explicit physical-event partition."""
        return tuple(
            identity.event for identity in self.identify(events).physical_events
        )

    def identify(
        self, events: tuple[DisasterEvent, ...]
    ) -> PhysicalEventIdentityResult:
        """Partition observations without order-dependent transitive merging.

        A connected equivalence component is merged only when every pair agrees.
        Non-clique components remain singleton physical events with explicit ambiguous
        assignments, preventing an A~B~C chain from coercing A and C together.
        """
        ordered = tuple(sorted(events, key=_event_order_key))
        compatible: dict[str, set[str]] = {
            event_observation_key(event): set() for event in ordered
        }
        by_key = {event_observation_key(event): event for event in ordered}
        for index, first in enumerate(ordered):
            first_key = event_observation_key(first)
            for second in ordered[index + 1 :]:
                if not self.same_physical_event(first, second):
                    continue
                second_key = event_observation_key(second)
                compatible[first_key].add(second_key)
                compatible[second_key].add(first_key)

        components: list[tuple[str, ...]] = []
        remaining = set(by_key)
        while remaining:
            start = min(remaining)
            queue = deque((start,))
            component: set[str] = set()
            while queue:
                current = queue.popleft()
                if current in component:
                    continue
                component.add(current)
                queue.extend(sorted(compatible[current] - component))
            remaining -= component
            components.append(tuple(sorted(component)))

        identities: list[PhysicalEventIdentity] = []
        ambiguous_assignments: list[EventObservationAssignment] = []
        for component_keys in sorted(components):
            pair_count = len(component_keys) * (len(component_keys) - 1) // 2
            actual_pairs = sum(len(compatible[key]) for key in component_keys) // 2
            is_complete = actual_pairs == pair_count
            groups = (
                (component_keys,)
                if is_complete
                else tuple((key,) for key in component_keys)
            )
            for group in groups:
                observations = tuple(by_key[key] for key in group)
                physical_event_id = _physical_event_id(observations)
                assignments: list[EventObservationAssignment] = []
                for key in group:
                    status = (
                        EventAssignmentStatus.ASSIGNED
                        if is_complete
                        else EventAssignmentStatus.AMBIGUOUS
                    )
                    assignment = EventObservationAssignment(
                        observation_key=key,
                        physical_event_id=physical_event_id,
                        status=status,
                        rationale=(
                            "All observations in the cluster satisfy the hazard policy "
                            "pairwise."
                            if len(group) > 1
                            else (
                                "No equivalent observation was found."
                                if is_complete
                                else "The observation matches multiple incompatible "
                                "cluster alternatives and was kept separate."
                            )
                        ),
                        compatible_observation_keys=tuple(sorted(compatible[key])),
                    )
                    assignments.append(assignment)
                    if status == EventAssignmentStatus.AMBIGUOUS:
                        ambiguous_assignments.append(assignment)
                identities.append(
                    PhysicalEventIdentity(
                        physical_event_id=physical_event_id,
                        event=self._merge_event(list(observations)),
                        observations=observations,
                        assignments=tuple(assignments),
                    )
                )
        return PhysicalEventIdentityResult(
            physical_events=tuple(
                sorted(identities, key=lambda item: item.physical_event_id)
            ),
            ambiguous_assignments=tuple(
                sorted(
                    ambiguous_assignments,
                    key=lambda item: item.observation_key,
                )
            ),
        )

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
                query.discriminator("event_id") is None
                or event.has_provider_id(query.discriminator("event_id") or "")
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
        identity_result = self.identify(candidates)
        identity_by_observation = {
            event_observation_key(identity.event): identity
            for identity in identity_result.physical_events
        }
        ranked = sorted(
            self._filtered(
                tuple(identity.event for identity in identity_result.physical_events),
                query,
                now,
            ),
            key=lambda item: (self.rank(item, query, now), event_observation_key(item)),
            reverse=True,
        )
        if not ranked:
            return EventResolution(
                None,
                (),
                False,
                "No candidate matched the bounded query window.",
                physical_events=identity_result.physical_events,
                ambiguous_assignments=identity_result.ambiguous_assignments,
            )
        selected = ranked[0]
        selected_identity = identity_by_observation[event_observation_key(selected)]
        alternatives = tuple(ranked[1:4])
        ambiguous = any(
            assignment.status == EventAssignmentStatus.AMBIGUOUS
            for assignment in selected_identity.assignments
        )
        if len(ranked) > 1:
            second = ranked[1]
            score_gap = self.rank(selected, query, now) - self.rank(second, query, now)
            ambiguous = ambiguous or (score_gap < self.ambiguity_threshold)
        return EventResolution(
            selected,
            alternatives,
            ambiguous,
            self.describe_selection(query, ambiguous),
            physical_events=identity_result.physical_events,
            selected_physical_event=selected_identity,
            ambiguous_assignments=identity_result.ambiguous_assignments,
        )


class EarthquakeEventPolicy(BaseEventPolicy):
    """Earthquake mainshock, equivalence, ranking, and ambiguity policy."""

    def _merge_event(self, events: list[DisasterEvent]) -> DisasterEvent:
        merged = super()._merge_event(events)
        earthquake_events = [
            event for event in events if isinstance(event, EarthquakeEvent)
        ]
        if not earthquake_events or not isinstance(merged, EarthquakeEvent):
            return merged
        return replace(
            merged,
            is_aftershock=any(event.is_aftershock for event in earthquake_events),
            parent_event_id=next(
                (
                    event.parent_event_id
                    for event in earthquake_events
                    if event.parent_event_id
                ),
                None,
            ),
            sequence_id=next(
                (event.sequence_id for event in earthquake_events if event.sequence_id),
                None,
            ),
        )

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
        query_magnitude = query.discriminator("magnitude")
        magnitude = _measurement(event, MeasurementKind.MAGNITUDE)
        if query_magnitude is not None and isinstance(magnitude, (int, float)):
            discriminator_bonus += max(
                0.0, 4.0 - abs(magnitude - float(query_magnitude)) * 8
            )
        significance = _measurement(event, MeasurementKind.PROVIDER_SIGNIFICANCE)
        return (
            recency * 0.6
            + (magnitude if isinstance(magnitude, (int, float)) else 0.0) * 2.0
            + _intensity_score(_measurement(event, MeasurementKind.INTENSITY)) * 1.5
            + (significance if isinstance(significance, (int, float)) else 0.0) / 500
            + discriminator_bonus
            - (3.0 if _is_aftershock(event) else 0.0)
        )

    def same_physical_event(self, first: DisasterEvent, second: DisasterEvent) -> bool:
        if (
            first.hazard != second.hazard
            or first.country.alpha3_code != second.country.alpha3_code
        ):
            return False
        if (
            _provider_identifiers(first) & _provider_identifiers(second)
            and abs((first.event_time - second.event_time).total_seconds()) <= 24 * 3600
        ):
            return True
        if super().same_physical_event(first, second):
            return True
        if abs((first.event_time - second.event_time).total_seconds()) > 90:
            return False
        distance = _distance_km(first, second)
        if distance is None or distance > 30:
            return False
        first_magnitude = _measurement(first, MeasurementKind.MAGNITUDE)
        second_magnitude = _measurement(second, MeasurementKind.MAGNITUDE)
        return not (
            isinstance(first_magnitude, (int, float))
            and isinstance(second_magnitude, (int, float))
            and abs(first_magnitude - second_magnitude) > 0.5
        )

    def same_sequence(self, first: DisasterEvent, second: DisasterEvent) -> bool:
        first_ids = _provider_identifiers(first)
        second_ids = _provider_identifiers(second)
        if (
            isinstance(first, EarthquakeEvent)
            and first.parent_event_id
            and first.parent_event_id.lower() in second_ids
        ):
            return True
        if (
            isinstance(second, EarthquakeEvent)
            and second.parent_event_id
            and second.parent_event_id.lower() in first_ids
        ):
            return True
        if (
            isinstance(first, EarthquakeEvent)
            and isinstance(second, EarthquakeEvent)
            and first.sequence_id
            and first.sequence_id == second.sequence_id
        ):
            return True
        if not (_is_aftershock(first) or _is_aftershock(second)):
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
        query_magnitude = query.discriminator("magnitude")
        if query_magnitude is not None:
            filtered = [
                event
                for event in filtered
                if isinstance(
                    magnitude := _measurement(event, MeasurementKind.MAGNITUDE),
                    (int, float),
                )
                and abs(magnitude - float(query_magnitude)) <= 0.25
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
                query.discriminator("event_id"),
                query.date_from,
                query.date_to,
                query.prefecture,
                query.city,
                query.latitude is not None and query.longitude is not None,
                query.discriminator("magnitude") is not None,
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
        ambiguous = resolution.ambiguous or (
            not self.same_sequence(resolution.selected, second)
            and (
                self.rank(resolution.selected, query, now)
                - self.rank(second, query, now)
                < self.ambiguity_threshold
                or _is_aftershock(second)
            )
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
        similar = resolution.ambiguous or (
            abs((resolution.selected.event_time - second.event_time).total_seconds())
            < self.ambiguity_threshold
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
    return policy.resolve(candidates, query, now=now)


def cluster_physical_events(
    events: tuple[DisasterEvent, ...], hazard: Hazard = Hazard.EARTHQUAKE
) -> tuple[DisasterEvent, ...]:
    """Cluster equivalent records using application-owned hazard policy."""
    return default_event_policy_registry().for_hazard(hazard).cluster(events)
