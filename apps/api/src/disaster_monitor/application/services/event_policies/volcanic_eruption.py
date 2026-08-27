"""Volcanic-eruption observation and event-resolution policy."""

from datetime import datetime, timedelta

from disaster_monitor.application.disaster import DisasterQuery
from disaster_monitor.application.services.event_identity import distance_km
from disaster_monitor.application.services.event_policies.default import (
    DefaultEventPolicy,
)
from disaster_monitor.domain.disaster import DisasterEvent


class VolcanicEruptionEventPolicy(DefaultEventPolicy):
    """Resolve ongoing WVAR eruptions by their current report publication."""

    _WVAR_SOURCE_ID = "smithsonian-usgs-volcanic-activity"
    _GDACS_SOURCE_ID = "gdacs-volcanic-eruptions"
    _MAXIMUM_IDENTITY_TIME_DELTA = timedelta(days=7)
    _MAXIMUM_IDENTITY_DISTANCE_KM = 8.0

    def _wvar_observation_time(self, event: DisasterEvent) -> datetime | None:
        if event.source.source_id != self._WVAR_SOURCE_ID:
            return None
        return event.source.updated_at or event.source.published_at

    def _matches_time_window(
        self, event: DisasterEvent, window_start: datetime, window_end: datetime
    ) -> bool:
        if super()._matches_time_window(event, window_start, window_end):
            return True
        observation_time = self._wvar_observation_time(event)
        return bool(
            observation_time is not None
            and window_start <= observation_time <= window_end
        )

    def rank(self, event: DisasterEvent, query: DisasterQuery, now: datetime) -> float:
        observation_time = self._wvar_observation_time(event)
        return (observation_time or event.event_time).timestamp()

    def same_physical_event(self, first: DisasterEvent, second: DisasterEvent) -> bool:
        if super().same_physical_event(first, second):
            return True
        if (
            first.disaster != second.disaster
            or first.country.alpha3_code != second.country.alpha3_code
            or frozenset((first.source.source_id, second.source.source_id))
            != frozenset((self._WVAR_SOURCE_ID, self._GDACS_SOURCE_ID))
        ):
            return False
        first_time = self._wvar_observation_time(first) or first.event_time
        second_time = self._wvar_observation_time(second) or second.event_time
        if (
            abs((first_time - second_time).total_seconds())
            > self._MAXIMUM_IDENTITY_TIME_DELTA.total_seconds()
        ):
            return False
        distance = distance_km(first, second)
        return distance is not None and distance <= self._MAXIMUM_IDENTITY_DISTANCE_KM

    def describe_selection(self, query: DisasterQuery, ambiguous: bool) -> str:
        if ambiguous:
            return "Multiple current WVAR eruption reports have similar timestamps."
        return "Selected the newest matching source-backed eruption report."
