"""Provider freshness policy and application-facing calculation."""

from collections.abc import Callable, Iterable, Mapping
from dataclasses import replace
from datetime import UTC, datetime, timedelta

from disaster_monitor.application.ports.provider_status import ProviderStatusReader
from disaster_monitor.domain.operations import ProviderFreshness, ProviderHealthState

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
        unconfigured_source_ids: Iterable[str] = (),
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
        self._unconfigured_source_ids = set(unconfigured_source_ids)

    async def list(self) -> tuple[ProviderFreshness, ...]:
        now = self._clock()
        if now.tzinfo is None:
            raise ValueError("Provider freshness time must be timezone-aware.")
        result = await self._repository.freshness(
            now=now,
            expectations=self._expectations,
        )
        read_projection = getattr(self._repository, "latest_incident_projection", None)
        projection_age: int | None = None
        if read_projection is not None:
            projection = await read_projection()
            if projection is not None:
                projection_age = max(
                    0, int((now - projection.retrieved_at).total_seconds())
                )
        return tuple(
            replace(
                item,
                health_state=ProviderHealthState.MISCONFIGURED,
                stale_projection_age_seconds=projection_age,
            )
            if item.source_id in self._unconfigured_source_ids
            else replace(item, stale_projection_age_seconds=projection_age)
            for item in result
        )
