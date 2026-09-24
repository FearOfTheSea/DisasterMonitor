"""Generic event filtering, ranking, resolution, and ambiguity mechanics."""

import re
import unicodedata
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from typing import Protocol

from disaster_monitor.application.disaster import (
    DisasterQuery,
    retrieval_time_bounds,
)
from disaster_monitor.application.evidence.event_identity import (
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
    IncidentActivityStatus,
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
    place_candidates: tuple[DisasterEvent, ...] = ()


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
    def words(text: str) -> list[str]:
        plain = "".join(
            character
            for character in unicodedata.normalize("NFKD", text.casefold())
            if not unicodedata.combining(character)
        )
        return re.sub(r"[^\w]+", " ", plain).split()

    wanted = words(value)
    actual = words(event.location)
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
        if window_start <= event.event_time <= window_end:
            return True
        source_update = event.source.updated_at or event.source.published_at
        return (
            event.activity_status is IncidentActivityStatus.ONGOING
            and source_update is not None
            and window_start <= source_update <= window_end
        )

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
        *,
        apply_place_filters: bool = True,
    ) -> list[DisasterEvent]:
        window_start, window_end = retrieval_time_bounds(
            query, now=now, end_margin=timedelta(minutes=5)
        )
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
        if apply_place_filters and query.prefecture:
            filtered = [
                event for event in filtered if location_matches(event, query.prefecture)
            ]
        if apply_place_filters and query.city:
            filtered = [
                event for event in filtered if location_matches(event, query.city)
            ]
        if apply_place_filters and query.location_hint:
            filtered = [
                event
                for event in filtered
                if location_matches(event, query.location_hint)
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
        place_filters = (query.prefecture, query.city, query.location_hint)
        eligible = self._filtered(
            tuple(identity.event for identity in identity_result.physical_events),
            query,
            now,
            apply_place_filters=False,
        )
        ranked = sorted(
            (
                event
                for event in eligible
                if all(
                    value is None
                    or any(
                        location_matches(observation, value)
                        for observation in identity_by_observation[
                            event_observation_key(event)
                        ].observations
                    )
                    for value in place_filters
                )
            ),
            key=lambda item: (self.rank(item, query, now), event_observation_key(item)),
            reverse=True,
        )
        if not ranked:
            place_candidates = (
                tuple(
                    sorted(
                        eligible,
                        key=lambda item: (
                            self.rank(item, query, now),
                            event_observation_key(item),
                        ),
                        reverse=True,
                    )[:3]
                )
                if any(place_filters)
                else ()
            )
            return EventResolution(
                None,
                (),
                False,
                "No candidate matched the bounded query window.",
                physical_events=identity_result.physical_events,
                ambiguous_assignments=identity_result.ambiguous_assignments,
                place_candidates=place_candidates,
            )
        selected = ranked[0]
        selected_identity = identity_by_observation[event_observation_key(selected)]
        matching_observations = tuple(
            observation
            for observation in selected_identity.observations
            if all(
                value is None or location_matches(observation, value)
                for value in place_filters
            )
        )
        if any(place_filters) and matching_observations:
            representative = max(
                matching_observations,
                key=lambda item: (
                    len(item.location),
                    item.source.effective_at,
                    event_observation_key(item),
                ),
            )
            selected = replace(
                selected,
                event_id=representative.event_id,
                location=representative.location,
                source=representative.source,
                location_source=representative.location_source,
            )
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
