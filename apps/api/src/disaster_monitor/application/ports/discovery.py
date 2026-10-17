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
