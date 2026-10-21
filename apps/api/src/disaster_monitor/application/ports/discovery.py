"""Consumer-owned discovery acquisition and scan persistence contracts."""

from collections.abc import AsyncIterator
from typing import Protocol

from disaster_monitor.domain.discovery import (
    DiscoveryBatch,
    DiscoveryRun,
    ReportingInterval,
)


class DiscoveryFeed(Protocol):
    source_id: str

    def discover(
        self, *, interval: ReportingInterval
    ) -> AsyncIterator[DiscoveryBatch]: ...


class DiscoveryStore(Protocol):
    async def save(self, run: DiscoveryRun) -> None: ...

    async def read(self, scan_id: str) -> DiscoveryRun | None: ...

    async def recent(self) -> tuple[DiscoveryRun, ...]: ...


class DiscoveryCapacityError(ValueError):
    """Retained discovery storage cannot admit more work without losing evidence."""

    def __init__(self) -> None:
        super().__init__(DISCOVERY_CAPACITY_NOTICE)


DISCOVERY_CAPACITY_NOTICE = (
    "Discovery storage capacity reached. Available results remain visible. "
    "Additional collected reporting and unfinished work are retained. "
    "Storage must be available before collection can continue."
)
