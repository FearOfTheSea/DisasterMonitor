"""Share public catalog snapshots without sharing mutable user requests."""

import asyncio
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta

from disaster_monitor.application.ground_imagery.catalog_search import (
    CatalogSearchResult,
    GroundImageryCatalogSearcher,
)
from disaster_monitor.application.ground_imagery.request_limits import (
    GroundImageryRateLimitExceeded,
    GroundImageryRequestLimiter,
)
from disaster_monitor.application.ground_imagery.temporal_policy import TemporalPlan
from disaster_monitor.domain.imagery.observations import Sensor
from disaster_monitor.domain.imagery.regions import MultiPolygon


@dataclass(frozen=True, slots=True)
class _Search:
    incident_id: str
    geometry: MultiPolygon
    plan: TemporalPlan
    sensors: tuple[Sensor, ...]


class SharedCatalogSearch:
    """Reuse up to five-minute snapshots with their original, visible cutoff.

    User regions, onset evidence, temporal policy, roles and sensors must match.
    Explicit refreshes do not silently become cache hits. At most two different
    searches execute concurrently, with eight admitted pending searches.
    """

    def __init__(
        self,
        searcher: GroundImageryCatalogSearcher,
        limiter: GroundImageryRequestLimiter | None,
        clock: Callable[[], datetime],
    ) -> None:
        self._searcher = searcher
        self._limiter = limiter
        self._clock = clock
        self._cache: OrderedDict[_Search, tuple[datetime, CatalogSearchResult]] = (
            OrderedDict()
        )
        self._tasks: dict[_Search, asyncio.Task[CatalogSearchResult]] = {}
        self._slots = asyncio.Semaphore(2)

    async def search(
        self,
        incident_id: str,
        geometry: MultiPolygon,
        plan: TemporalPlan,
        sensors: tuple[Sensor, ...],
        *,
        allow_cached: bool = True,
    ) -> tuple[TemporalPlan, CatalogSearchResult, bool]:
        query = _Search(incident_id, geometry, plan, sensors)
        if allow_cached:
            for old, (created, result) in reversed(self._cache.items()):
                freshness = (
                    timedelta(seconds=30)
                    if any(status.failure_code for status in result.statuses)
                    else timedelta(minutes=5)
                )
                if self._clock() - created < freshness and _compatible(old, query):
                    return old.plan, result, True
            for old, pending_task in self._tasks.items():
                if _compatible(old, query):
                    return old.plan, await asyncio.shield(pending_task), True
        if len(self._tasks) >= 8:
            raise GroundImageryRateLimitExceeded(
                "Imagery search queue is full. Retry shortly.", 10
            )
        # Exact work can also be shared by simultaneous explicit refresh callers.
        task = self._tasks.get(query)
        reused = task is not None
        if task is None:
            task = asyncio.create_task(self._execute(query))
            self._tasks[query] = task
            task.add_done_callback(
                lambda done: None if done.cancelled() else done.exception()
            )
        return plan, await asyncio.shield(task), reused

    async def _execute(self, query: _Search) -> CatalogSearchResult:
        try:
            async with asyncio.timeout(120):
                async with self._slots:
                    if self._limiter is not None:
                        await self._limiter.claim_catalog_search(query.incident_id)
                    result = await self._searcher.search(
                        query.geometry, query.plan, query.sensors
                    )
            self._cache[query] = (self._clock(), result)
            while len(self._cache) > 64:
                self._cache.popitem(last=False)
            return result
        finally:
            self._tasks.pop(query, None)

    async def aclose(self) -> None:
        tasks = tuple(self._tasks.values())
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


def _compatible(old: _Search, new: _Search) -> bool:
    if (old.incident_id, old.geometry, old.sensors) != (
        new.incident_id,
        new.geometry,
        new.sensors,
    ):
        return False
    first, second = old.plan, new.plan
    if (first.onset, first.impact_end, first.policy_version, first.recovery_anchor) != (
        second.onset,
        second.impact_end,
        second.policy_version,
        second.recovery_anchor,
    ):
        return False
    if (
        not timedelta(0)
        <= second.reference_time - first.reference_time
        < timedelta(minutes=5)
    ):
        return False
    if len(first.windows) != len(second.windows):
        return False
    return all(
        (a.role, a.sensor, a.is_empty) == (b.role, b.sensor, b.is_empty)
        and all(
            abs((x - y).total_seconds()) < 300
            for x, y in zip(
                (a.start, a.end, a.expanded_start, a.expanded_end),
                (b.start, b.end, b.expanded_start, b.expanded_end),
                strict=True,
            )
        )
        for a, b in zip(first.windows, second.windows, strict=True)
    )
