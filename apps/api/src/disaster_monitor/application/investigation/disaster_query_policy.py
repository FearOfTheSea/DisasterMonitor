"""Disaster-owned parsing for discriminators beyond neutral geography/time."""

import re
from typing import Protocol

from disaster_monitor.application.disaster import EventDiscriminator
from disaster_monitor.domain.disaster import Disaster


class DisasterQueryPolicy(Protocol):
    def discriminators(self, text: str) -> tuple[EventDiscriminator, ...]: ...


class DefaultDisasterQueryPolicy:
    def discriminators(self, text: str) -> tuple[EventDiscriminator, ...]:
        return ()


class EarthquakeQueryPolicy(DefaultDisasterQueryPolicy):
    _MAGNITUDE = re.compile(r"\b(?:magnitude|mag\.?|m)\s*([0-9]+(?:\.[0-9]+)?)\b", re.I)
    _EVENT_ID = re.compile(r"\bus\d{6,}\b", re.I)

    def discriminators(self, text: str) -> tuple[EventDiscriminator, ...]:
        values: list[EventDiscriminator] = []
        magnitude = self._MAGNITUDE.search(text)
        if magnitude:
            values.append(EventDiscriminator("magnitude", magnitude.group(1)))
        event_id = self._EVENT_ID.search(text)
        if event_id:
            values.append(EventDiscriminator("event_id", event_id.group(0)))
        return tuple(values)


class DisasterQueryPolicyRegistry:
    def __init__(self, policies: dict[Disaster, DisasterQueryPolicy]) -> None:
        self._policies = dict(policies)
        self._default = DefaultDisasterQueryPolicy()

    def for_disaster(self, disaster: Disaster) -> DisasterQueryPolicy:
        return self._policies.get(disaster, self._default)


def default_disaster_query_policies() -> DisasterQueryPolicyRegistry:
    return DisasterQueryPolicyRegistry({Disaster.EARTHQUAKE: EarthquakeQueryPolicy()})
