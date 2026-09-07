"""Ports for durable evidence snapshots, jobs, history, and attribution."""

from datetime import datetime, timedelta
from typing import Protocol

from disaster_monitor.domain.operations import (
    ProviderFreshness,
)


class ProviderStatusReader(Protocol):
    async def freshness(
        self,
        *,
        now: datetime,
        expectations: dict[str, timedelta],
    ) -> tuple[ProviderFreshness, ...]: ...
