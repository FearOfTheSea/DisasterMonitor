"""Provider freshness policy and application-facing calculation."""

from collections.abc import Callable, Mapping
from datetime import UTC, datetime, timedelta

from disaster_monitor.application.ports.operational_state import OperationalRepository
from disaster_monitor.domain.operations import ProviderFreshness

DEFAULT_PROVIDER_FRESHNESS_EXPECTATIONS: Mapping[str, timedelta] = {
    "usgs-earthquakes": timedelta(minutes=15),
    "gdacs-tropical-cyclones": timedelta(hours=1),
}


class ProviderFreshnessService:
    """Calculate source freshness against application-owned expectations."""

    def __init__(
        self,
        repository: OperationalRepository,
        *,
        expectations: Mapping[str, timedelta] = (
            DEFAULT_PROVIDER_FRESHNESS_EXPECTATIONS
        ),
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._repository = repository
        self._expectations = dict(expectations)
        self._clock = clock

    async def list(self) -> tuple[ProviderFreshness, ...]:
        now = self._clock()
        if now.tzinfo is None:
            raise ValueError("Provider freshness time must be timezone-aware.")
        return await self._repository.freshness(
            now=now,
            expectations=self._expectations,
        )
