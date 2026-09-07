"""Ports for durable evidence snapshots, jobs, history, and attribution."""

from typing import Protocol

from disaster_monitor.domain.operations import (
    EventObservationLinkRecord,
    NormalizedObservationRecord,
    PhysicalEventRecord,
    WorldStateVersionRecord,
)


class EvidenceWriter(Protocol):
    async def append_observations(
        self, observations: tuple[NormalizedObservationRecord, ...]
    ) -> int: ...

    async def append_physical_event(self, event: PhysicalEventRecord) -> bool: ...

    async def append_event_links(
        self, links: tuple[EventObservationLinkRecord, ...]
    ) -> int: ...

    async def append_world_state(self, state: WorldStateVersionRecord) -> bool: ...
