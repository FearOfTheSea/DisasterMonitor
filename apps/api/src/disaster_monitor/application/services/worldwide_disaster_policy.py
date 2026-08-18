"""Hazard policies for worldwide normalization and event selection."""

import re
from datetime import UTC, datetime
from typing import Protocol

from disaster_monitor.application.disaster import (
    WorldwideDisasterEvent,
    WorldwideDisasterQuery,
    WorldwideSelectionIntent,
)
from disaster_monitor.domain.disaster import Hazard, MeasurementKind


def _measurement(
    event: WorldwideDisasterEvent, kind: MeasurementKind
) -> float | str | None:
    for measurement in event.measurements:
        if measurement.kind is kind:
            return measurement.value
    return None


class WorldwideDisasterPolicy(Protocol):
    """Hazard-owned worldwide query and selection semantics."""

    def selection_for(self, question: str) -> WorldwideSelectionIntent: ...

    def select(
        self,
        events: tuple[WorldwideDisasterEvent, ...],
        query: WorldwideDisasterQuery,
    ) -> WorldwideDisasterEvent | None: ...

    def describe_selection(
        self,
        event: WorldwideDisasterEvent,
        query: WorldwideDisasterQuery,
    ) -> str: ...

    def response_type(self, query: WorldwideDisasterQuery) -> str: ...


class DefaultWorldwideDisasterPolicy:
    """Shared latest-event behavior for hazards without special ranking rules."""

    def selection_for(self, question: str) -> WorldwideSelectionIntent:
        return WorldwideSelectionIntent.LATEST

    def select(
        self,
        events: tuple[WorldwideDisasterEvent, ...],
        query: WorldwideDisasterQuery,
    ) -> WorldwideDisasterEvent | None:
        if not events:
            return None
        return max(events, key=lambda event: event.event_time)

    def describe_selection(
        self,
        event: WorldwideDisasterEvent,
        query: WorldwideDisasterQuery,
    ) -> str:
        return (
            f"{event.source.publisher} reports the latest matching worldwide "
            f"{query.hazard.value} event as "
            f"{event.event_id}: {event.location}; event time "
            f"{_utc_text(event.event_time)}."
        )

    def response_type(self, query: WorldwideDisasterQuery) -> str:
        return "current_disaster_worldwide"


class EarthquakeWorldwideDisasterPolicy(DefaultWorldwideDisasterPolicy):
    """Earthquake-specific ranking and wording kept outside generic orchestration."""

    def selection_for(self, question: str) -> WorldwideSelectionIntent:
        return (
            WorldwideSelectionIntent.STRONGEST
            if _STRONGEST_MARKERS.search(question)
            else WorldwideSelectionIntent.LATEST
        )

    def select(
        self,
        events: tuple[WorldwideDisasterEvent, ...],
        query: WorldwideDisasterQuery,
    ) -> WorldwideDisasterEvent | None:
        if not events:
            return None
        if query.selection_intent is WorldwideSelectionIntent.STRONGEST:
            return max(
                events,
                key=lambda event: (
                    _measurement(event, MeasurementKind.MAGNITUDE)
                    if isinstance(
                        _measurement(event, MeasurementKind.MAGNITUDE), (int, float)
                    )
                    else float("-inf"),
                    _measurement(event, MeasurementKind.PROVIDER_SIGNIFICANCE)
                    if isinstance(
                        _measurement(event, MeasurementKind.PROVIDER_SIGNIFICANCE),
                        (int, float),
                    )
                    else float("-inf"),
                    event.event_time,
                    event.event_id,
                ),
            )
        return max(
            events,
            key=lambda event: (
                event.event_time,
                _measurement(event, MeasurementKind.MAGNITUDE)
                if isinstance(
                    _measurement(event, MeasurementKind.MAGNITUDE), (int, float)
                )
                else float("-inf"),
                event.event_id,
            ),
        )

    def describe_selection(
        self,
        event: WorldwideDisasterEvent,
        query: WorldwideDisasterQuery,
    ) -> str:
        label = (
            "strongest"
            if query.selection_intent is WorldwideSelectionIntent.STRONGEST
            else "latest"
        )
        magnitude_value = _measurement(event, MeasurementKind.MAGNITUDE)
        magnitude = (
            f" magnitude {magnitude_value:g}"
            if isinstance(magnitude_value, (int, float))
            else " unknown magnitude"
        )
        return (
            f"{event.source.publisher} identifies the {label} matching worldwide "
            "earthquake as "
            f"{event.event_id}: {event.location}; event time "
            f"{_utc_text(event.event_time)};{magnitude}."
        )

    def response_type(self, query: WorldwideDisasterQuery) -> str:
        return "current_disaster_global_earthquake"


class WorldwideDisasterPolicyRegistry:
    """Resolve a hazard to its worldwide policy without branching in orchestration."""

    def __init__(self, policies: dict[Hazard, WorldwideDisasterPolicy]) -> None:
        self._policies = dict(policies)
        self._default = DefaultWorldwideDisasterPolicy()

    def for_hazard(self, hazard: Hazard) -> WorldwideDisasterPolicy:
        return self._policies.get(hazard, self._default)


def default_worldwide_disaster_policy_registry() -> WorldwideDisasterPolicyRegistry:
    return WorldwideDisasterPolicyRegistry(
        {Hazard.EARTHQUAKE: EarthquakeWorldwideDisasterPolicy()}
    )


def _utc_text(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


_STRONGEST_MARKERS = re.compile(
    r"\b(?:strongest|largest|biggest|highest[- ]magnitude|most powerful)\b",
    re.I,
)
