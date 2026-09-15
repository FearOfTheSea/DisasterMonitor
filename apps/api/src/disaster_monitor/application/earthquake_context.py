"""Application use case for bounded USGS event-product context."""

from collections.abc import Callable
from datetime import UTC, datetime

from disaster_monitor.application.ports.earthquake_context import (
    EarthquakeContextReader,
)
from disaster_monitor.domain.earthquake_context import EarthquakeContext


class EarthquakeContextService:
    def __init__(
        self,
        reader: EarthquakeContextReader,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._reader = reader
        self._clock = clock

    async def execute(self, event_id: str) -> EarthquakeContext:
        return await self._reader.fetch(event_id, now=self._clock())

    async def aclose(self) -> None:
        await self._reader.aclose()
