"""Hazard-owned parsing for discriminators beyond neutral geography/time."""

import re
from typing import Protocol

from disaster_monitor.application.disaster import EventDiscriminator
from disaster_monitor.domain.disaster import Hazard


class HazardQueryPolicy(Protocol):
    def discriminators(self, text: str) -> tuple[EventDiscriminator, ...]: ...


class DefaultHazardQueryPolicy:
    def discriminators(self, text: str) -> tuple[EventDiscriminator, ...]:
        return ()


class EarthquakeQueryPolicy(DefaultHazardQueryPolicy):
    _MAGNITUDE = re.compile(r"\b(?:magnitude|mag\.?|m)\s*([0-9]+(?:\.[0-9]+)?)\b", re.I)
    _EVENT_ID = re.compile(r"\b(?:us\d{6,}|jma[:_-]?[A-Za-z0-9_-]+)\b", re.I)

    def discriminators(self, text: str) -> tuple[EventDiscriminator, ...]:
        values: list[EventDiscriminator] = []
        magnitude = self._MAGNITUDE.search(text)
        if magnitude:
            values.append(EventDiscriminator("magnitude", magnitude.group(1)))
        event_id = self._EVENT_ID.search(text)
        if event_id:
            values.append(EventDiscriminator("event_id", event_id.group(0)))
        return tuple(values)


class HazardQueryPolicyRegistry:
    def __init__(self, policies: dict[Hazard, HazardQueryPolicy]) -> None:
        self._policies = dict(policies)
        self._default = DefaultHazardQueryPolicy()

    def for_hazard(self, hazard: Hazard) -> HazardQueryPolicy:
        return self._policies.get(hazard, self._default)


def default_hazard_query_policies() -> HazardQueryPolicyRegistry:
    return HazardQueryPolicyRegistry({Hazard.EARTHQUAKE: EarthquakeQueryPolicy()})
