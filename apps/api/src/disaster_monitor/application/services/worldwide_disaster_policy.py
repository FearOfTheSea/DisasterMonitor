"""Hazard policies for worldwide normalization and event selection."""

import re
from datetime import UTC, datetime
from typing import Protocol

from disaster_monitor.application.disaster import (
    WorldwideDisasterEvent,
    WorldwideDisasterQuery,
)
from disaster_monitor.domain.disaster import Hazard


class WorldwideDisasterPolicy(Protocol):
    """Hazard-owned worldwide query and selection semantics."""

    def selection_for(self, question: str) -> str: ...

    def select(
        self, events: tuple[WorldwideDisasterEvent, ...], query: WorldwideDisasterQuery
    ) -> WorldwideDisasterEvent | None: ...

    def describe_selection(
        self, event: WorldwideDisasterEvent, query: WorldwideDisasterQuery
    ) -> str: ...

    def response_type(self, query: WorldwideDisasterQuery) -> str: ...


class DefaultWorldwideDisasterPolicy:
    """Shared latest-event behavior for hazards without special ranking rules."""

    def selection_for(self, question: str) -> str:
        return "latest"

    def select(
        self, events: tuple[WorldwideDisasterEvent, ...], query: WorldwideDisasterQuery
    ) -> WorldwideDisasterEvent | None:
        if not events:
            return None
        return max(events, key=lambda event: event.event_time)

    def describe_selection(
        self, event: WorldwideDisasterEvent, query: WorldwideDisasterQuery
    ) -> str:
        return (
            f"The latest matching worldwide {query.hazard.value} event is "
            f"{event.event_id}: {event.location}; event time "
            f"{_utc_text(event.event_time)}."
        )

    def response_type(self, query: WorldwideDisasterQuery) -> str:
        return "current_disaster_worldwide"


class EarthquakeWorldwideDisasterPolicy(DefaultWorldwideDisasterPolicy):
    """Earthquake-specific ranking and wording kept outside generic orchestration."""

    def selection_for(self, question: str) -> str:
        return "strongest" if _STRONGEST_MARKERS.search(question) else "latest"

    def select(
        self, events: tuple[WorldwideDisasterEvent, ...], query: WorldwideDisasterQuery
    ) -> WorldwideDisasterEvent | None:
        if not events:
            return None
        if query.selection == "strongest":
            return max(
                events,
                key=lambda event: (
                    event.magnitude if event.magnitude is not None else float("-inf"),
                    event.significance
                    if event.significance is not None
                    else float("-inf"),
                    event.event_time,
                    event.event_id,
                ),
            )
        return max(
            events,
            key=lambda event: (
                event.event_time,
                event.magnitude if event.magnitude is not None else float("-inf"),
                event.event_id,
            ),
        )

    def describe_selection(
        self, event: WorldwideDisasterEvent, query: WorldwideDisasterQuery
    ) -> str:
        label = "strongest" if query.selection == "strongest" else "latest"
        magnitude = (
            f" magnitude {event.magnitude:g}"
            if event.magnitude is not None
            else " unknown magnitude"
        )
        return (
            f"USGS identifies the {label} matching worldwide earthquake as "
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
