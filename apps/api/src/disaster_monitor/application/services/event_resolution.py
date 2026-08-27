"""Compatibility facade for decomposed event identity and resolution services."""

from datetime import datetime

from disaster_monitor.application.disaster import DisasterQuery
from disaster_monitor.application.services.event_identity import event_observation_key
from disaster_monitor.application.services.event_policies import (
    DefaultEventPolicy,
    EarthquakeEventPolicy,
    EventPolicyRegistry,
    FloodEventPolicy,
    VolcanicEruptionEventPolicy,
    WildfireEventPolicy,
    default_event_policy_registry,
)
from disaster_monitor.application.services.event_resolution_core import (
    BaseEventPolicy,
    EventPolicy,
    EventResolution,
)
from disaster_monitor.domain.disaster import DisasterEvent


def resolve_recent_event(
    candidates: tuple[DisasterEvent, ...],
    query: DisasterQuery,
    *,
    now: datetime,
) -> EventResolution:
    """Resolve a recent event through the typed disaster policy registry."""
    return (
        default_event_policy_registry()
        .for_disaster(query.disaster)
        .resolve(candidates, query, now=now)
    )


def cluster_physical_events(
    events: tuple[DisasterEvent, ...],
) -> tuple[DisasterEvent, ...]:
    """Cluster observations after enforcing a single disaster type."""
    if not events:
        raise ValueError("Physical-event clustering requires at least one event.")
    disasters = {event.disaster for event in events}
    if len(disasters) != 1:
        raise ValueError(
            "Physical-event clustering requires one disaster across all events."
        )
    return (
        default_event_policy_registry()
        .for_disaster(next(iter(disasters)))
        .cluster(events)
    )


__all__ = [
    "BaseEventPolicy",
    "DefaultEventPolicy",
    "EarthquakeEventPolicy",
    "EventPolicy",
    "EventPolicyRegistry",
    "EventResolution",
    "FloodEventPolicy",
    "VolcanicEruptionEventPolicy",
    "WildfireEventPolicy",
    "cluster_physical_events",
    "default_event_policy_registry",
    "event_observation_key",
    "resolve_recent_event",
]
