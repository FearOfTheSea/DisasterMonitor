"""Ports for durable evidence snapshots, jobs, history, and attribution."""

from datetime import datetime, timedelta
from typing import Protocol

from disaster_monitor.domain.operations import (
    ProviderAttempt,
    ProviderFreshness,
)


class ProviderStatusReader(Protocol):
    async def provider_attempts(
        self, *, source_id: str, limit: int = 100
    ) -> tuple[ProviderAttempt, ...]: ...

    async def freshness(
        self,
        *,
        now: datetime,
        expectations: dict[str, timedelta],
    ) -> tuple[ProviderFreshness, ...]: ...


class ProviderAttemptWriter(Protocol):
    async def record_provider_attempt(self, attempt: ProviderAttempt) -> None: ...
