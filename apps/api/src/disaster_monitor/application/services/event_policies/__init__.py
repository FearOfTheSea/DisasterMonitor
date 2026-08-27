"""Typed disaster-specific event policies and registry."""

from disaster_monitor.application.services.event_policies.default import (
    DefaultEventPolicy,
)
from disaster_monitor.application.services.event_policies.earthquake import (
    EarthquakeEventPolicy,
)
from disaster_monitor.application.services.event_policies.flood import FloodEventPolicy
from disaster_monitor.application.services.event_policies.volcanic_eruption import (
    VolcanicEruptionEventPolicy,
)
from disaster_monitor.application.services.event_policies.wildfire import (
    WildfireEventPolicy,
)
from disaster_monitor.application.services.event_resolution_core import EventPolicy
from disaster_monitor.domain.disaster import Disaster


class EventPolicyRegistry:
    """Resolve a typed disaster to a dedicated or conservative event policy."""

    def __init__(
        self, policies: dict[Disaster, EventPolicy], default: EventPolicy
    ) -> None:
        self._policies = dict(policies)
        self._default = default

    def for_disaster(self, disaster: Disaster) -> EventPolicy:
        return self._policies.get(disaster, self._default)


def default_event_policy_registry() -> EventPolicyRegistry:
    return EventPolicyRegistry(
        {
            Disaster.EARTHQUAKE: EarthquakeEventPolicy(),
            Disaster.FLOOD: FloodEventPolicy(),
            Disaster.WILDFIRE: WildfireEventPolicy(),
            Disaster.VOLCANIC_ERUPTION: VolcanicEruptionEventPolicy(),
        },
        DefaultEventPolicy(),
    )


__all__ = [
    "DefaultEventPolicy",
    "EarthquakeEventPolicy",
    "EventPolicyRegistry",
    "FloodEventPolicy",
    "VolcanicEruptionEventPolicy",
    "WildfireEventPolicy",
    "default_event_policy_registry",
]
