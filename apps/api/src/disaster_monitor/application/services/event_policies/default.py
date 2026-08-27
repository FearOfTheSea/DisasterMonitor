"""Conservative default and reusable cross-provider event policy."""

from dataclasses import replace
from datetime import datetime, timedelta

from disaster_monitor.application.disaster import DisasterQuery
from disaster_monitor.application.services.event_identity import distance_km
from disaster_monitor.application.services.event_resolution_core import (
    BaseEventPolicy,
    EventResolution,
)
from disaster_monitor.domain.disaster import DisasterEvent


class DefaultEventPolicy(BaseEventPolicy):
    """Conservative policy for disasters without dedicated equivalence rules."""

    ambiguity_threshold = 6.0 * 3600

    def rank(self, event: DisasterEvent, query: DisasterQuery, now: datetime) -> float:
        return event.event_time.timestamp()

    def describe_selection(self, query: DisasterQuery, ambiguous: bool) -> str:
        if ambiguous:
            return (
                f"Multiple independent {query.disaster.value} events have similarly "
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


class CrossProviderGeoTemporalEventPolicy(DefaultEventPolicy):
    """Equate a bounded provider pair using explicit time and distance limits."""

    source_pair: frozenset[str]
    maximum_time_delta: timedelta
    maximum_distance_km: float

    def _identity_time(self, event: DisasterEvent) -> datetime:
        return event.event_time

    def same_physical_event(self, first: DisasterEvent, second: DisasterEvent) -> bool:
        if super().same_physical_event(first, second):
            return True
        if (
            first.disaster != second.disaster
            or first.country.alpha3_code != second.country.alpha3_code
            or frozenset((first.source.source_id, second.source.source_id))
            != self.source_pair
        ):
            return False
        if (
            abs(
                (
                    self._identity_time(first) - self._identity_time(second)
                ).total_seconds()
            )
            > self.maximum_time_delta.total_seconds()
        ):
            return False
        distance = distance_km(first, second)
        return distance is not None and distance <= self.maximum_distance_km
