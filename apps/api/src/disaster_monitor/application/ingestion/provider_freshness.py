"""Provider freshness policy and application-facing calculation."""

from collections.abc import Callable, Iterable, Mapping
from datetime import UTC, datetime, timedelta

from disaster_monitor.application.ports.provider_status import ProviderStatusReader
from disaster_monitor.domain.operations import ProviderFreshness

DEFAULT_PROVIDER_FRESHNESS_EXPECTATIONS: Mapping[str, timedelta] = {
    "usgs-earthquakes": timedelta(minutes=15),
    "gdacs-tropical-cyclones": timedelta(hours=1),
}
DEFAULT_UNMEASURED_PROVIDER_FRESHNESS = timedelta(hours=1)


class ProviderFreshnessService:
    """Calculate source freshness against application-owned expectations."""

    def __init__(
        self,
        repository: ProviderStatusReader,
        *,
        expectations: Mapping[str, timedelta] = (
            DEFAULT_PROVIDER_FRESHNESS_EXPECTATIONS
        ),
        source_ids: Iterable[str] = (),
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._repository = repository
        self._expectations = dict(expectations)
        for source_id in source_ids:
            if source_id.strip():
                self._expectations.setdefault(
                    source_id, DEFAULT_UNMEASURED_PROVIDER_FRESHNESS
                )
        self._clock = clock

    async def list(self) -> tuple[ProviderFreshness, ...]:
        now = self._clock()
        if now.tzinfo is None:
            raise ValueError("Provider freshness time must be timezone-aware.")
        return await self._repository.freshness(
            now=now,
            expectations=self._expectations,
        )
