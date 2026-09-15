"""Event-scoped authoritative earthquake product retrieval boundary."""

from datetime import datetime
from typing import Protocol

from disaster_monitor.domain.earthquake_context import EarthquakeContext


class EarthquakeContextProviderError(RuntimeError):
    """The bounded authoritative product request could not be completed."""


class EarthquakeContextReader(Protocol):
    async def fetch(self, event_id: str, *, now: datetime) -> EarthquakeContext: ...

    async def aclose(self) -> None: ...
