"""Generic event filtering, ranking, resolution, and ambiguity mechanics."""

import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol

from disaster_monitor.application.disaster import DisasterQuery
from disaster_monitor.application.services.event_identity import (
    distance_to_coordinates,
    event_observation_key,
    identify_physical_events,
    merge_event,
    provider_identifiers,
)
from disaster_monitor.domain.disaster import (
    DisasterEvent,
    EventAssignmentStatus,
    EventObservationAssignment,
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
    """Typed policy supplying equivalence and ranking to generic mechanics."""

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


def location_matches(event: DisasterEvent, value: str) -> bool:
    wanted = re.sub(r"[^a-z0-9]+", " ", value.lower()).split()
    actual = re.sub(r"[^a-z0-9]+", " ", event.location.lower()).split()
    return bool(wanted) and all(token in actual for token in wanted)


class BaseEventPolicy:
    """Shared conservative filtering and resolution mechanics."""

    ambiguity_threshold = 0.6

    def rank(self, event: DisasterEvent, query: DisasterQuery, now: datetime) -> float:
        raise NotImplementedError

    def describe_selection(self, query: DisasterQuery, ambiguous: bool) -> str:
        raise NotImplementedError

    def _merge_event(self, events: list[DisasterEvent]) -> DisasterEvent:
        return merge_event(events)

    def _matches_time_window(
        self, event: DisasterEvent, window_start: datetime, window_end: datetime
    ) -> bool:
        return window_start <= event.event_time <= window_end

    def same_physical_event(self, first: DisasterEvent, second: DisasterEvent) -> bool:
        if (
            first.disaster != second.disaster
            or first.country.alpha3_code != second.country.alpha3_code
        ):
            return False
        shared_identifiers = provider_identifiers(first) & provider_identifiers(second)
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
        return identify_physical_events(
            events,
            equivalent=self.same_physical_event,
            merge=self._merge_event,
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
            if event.disaster == query.disaster
            and event.country.alpha3_code == query.country.alpha3_code
            and self._matches_time_window(event, window_start, window_end)
            and (
                query.discriminator("event_id") is None
                or event.has_provider_id(query.discriminator("event_id") or "")
            )
        ]
        if query.prefecture:
            filtered = [
                event for event in filtered if location_matches(event, query.prefecture)
            ]
        if query.city:
            filtered = [
                event for event in filtered if location_matches(event, query.city)
            ]
        if query.latitude is not None and query.longitude is not None:
            filtered = [
                event
                for event in filtered
                if (
                    distance := distance_to_coordinates(
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
            assignment.status is EventAssignmentStatus.AMBIGUOUS
            for assignment in selected_identity.assignments
        )
        if len(ranked) > 1:
            second = ranked[1]
            score_gap = self.rank(selected, query, now) - self.rank(second, query, now)
            ambiguous = ambiguous or score_gap < self.ambiguity_threshold
        return EventResolution(
            selected,
            alternatives,
            ambiguous,
            self.describe_selection(query, ambiguous),
            physical_events=identity_result.physical_events,
            selected_physical_event=selected_identity,
            ambiguous_assignments=identity_result.ambiguous_assignments,
        )
