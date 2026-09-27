"""Deployment-wide admission limits for costly Ground catalog and render work."""

from __future__ import annotations

import asyncio
from collections import deque
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from math import ceil

from disaster_monitor.application.ground_imagery.errors import GroundImageryError

_HOUR = timedelta(hours=1)
_DAY = timedelta(days=1)


class GroundImageryRateLimitExceeded(GroundImageryError):
    """The deployment must wait before admitting more provider work."""

    def __init__(self, detail: str, retry_after_seconds: int) -> None:
        super().__init__(detail)
        self.retry_after_seconds = retry_after_seconds


class GroundImageryRequestLimiter:
    """Bound searches and preparations on the single-process local deployment.

    This is deliberately deployment-wide. The public HTTP API has no trusted
    per-user identity, so client-supplied owner scopes cannot partition a quota.
    """

    def __init__(
        self,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._clock = clock
        self._lock = asyncio.Lock()
        self._searches: deque[datetime] = deque()
        self._preparations: deque[datetime] = deque()
        self._last_search_by_incident: dict[str, datetime] = {}

    async def claim_catalog_search(self, incident_id: str) -> None:
        now = self._clock()
        async with self._lock:
            self._trim(self._searches, now)
            last = self._last_search_by_incident.get(incident_id)
            if last is not None and now - last < _HOUR:
                raise GroundImageryRateLimitExceeded(
                    "This incident was searched recently. Try again later.",
                    _retry_after(last + _HOUR, now),
                )
            _enforce(self._searches, now, hourly=6, daily=24, label="catalog searches")
            self._searches.append(now)
            self._last_search_by_incident[incident_id] = now
            self._last_search_by_incident = {
                key: searched_at
                for key, searched_at in self._last_search_by_incident.items()
                if now - searched_at < _HOUR
            }

    async def claim_preparation(self) -> None:
        now = self._clock()
        async with self._lock:
            self._trim(self._preparations, now)
            _enforce(
                self._preparations,
                now,
                hourly=4,
                daily=12,
                label="image preparations",
            )
            self._preparations.append(now)

    @staticmethod
    def _trim(times: deque[datetime], now: datetime) -> None:
        while times and now - times[0] >= _DAY:
            times.popleft()


def _enforce(
    times: deque[datetime],
    now: datetime,
    *,
    hourly: int,
    daily: int,
    label: str,
) -> None:
    hourly_times = tuple(value for value in times if now - value < _HOUR)
    deadlines = []
    if len(hourly_times) >= hourly:
        deadlines.append(hourly_times[-hourly] + _HOUR)
    if len(times) >= daily:
        deadlines.append(times[-daily] + _DAY)
    if deadlines:
        raise GroundImageryRateLimitExceeded(
            f"The Ground view limit for {label} has been reached. Try again later.",
            _retry_after(max(deadlines), now),
        )


def _retry_after(deadline: datetime, now: datetime) -> int:
    return max(1, ceil((deadline - now).total_seconds()))
