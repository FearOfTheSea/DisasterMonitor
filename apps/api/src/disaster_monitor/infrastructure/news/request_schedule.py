"""Bounded metadata requests with pacing, shared work, and short fresh caching."""

import asyncio
import json
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from time import monotonic

import httpx


@dataclass(slots=True)
class NewsRequestError(Exception):
    reason: str
    http_status: int | None = None
    retry_after_seconds: float | None = None

    def __str__(self) -> str:
        status = f" HTTP {self.http_status}" if self.http_status else ""
        retry = (
            f"; retry after {self.retry_after_seconds:g} seconds"
            if self.retry_after_seconds is not None
            else ""
        )
        return f"{self.reason}{status}{retry}"


@dataclass(frozen=True, slots=True)
class NewsJsonSnapshot:
    payload: object
    retrieved_at: datetime
    cached: bool = False


class ScheduledNewsJson:
    """One provider client's bounded request schedule; never retry a refusal in a loop.

    A cancelled subscriber cannot cancel compatible work needed by another scan.
    Successful responses live for five minutes; failed responses are never cached.
    Advertised Retry-After is a minimum, including when it exceeds our scan deadline.
    """

    def __init__(
        self,
        client: httpx.AsyncClient,
        *,
        minimum_interval: float = 1,
        clock: Callable[[], float] = monotonic,
        cache_seconds: float = 300,
        maximum_bytes: int = 2_000_000,
        timeout_seconds: float = 15,
    ) -> None:
        self._client = client
        self._interval = minimum_interval
        self._clock = clock
        self._ttl = cache_seconds
        self._maximum_bytes = maximum_bytes
        self._timeout = timeout_seconds
        self._cache: OrderedDict[str, tuple[float, NewsJsonSnapshot]] = OrderedDict()
        self._tasks: dict[str, asyncio.Task[NewsJsonSnapshot]] = {}
        self._lock = asyncio.Lock()
        self._next_request = 0.0
        self._blocked_until = 0.0
        self._failure: NewsRequestError | None = None

    async def get(self, url: str, params: dict[str, str]) -> NewsJsonSnapshot:
        key = str(httpx.URL(url, params=sorted(params.items())))
        cached = self._cache.get(key)
        if cached and self._clock() - cached[0] < self._ttl:
            return replace(cached[1], cached=True)
        task = self._tasks.get(key)
        if task is None:
            if len(self._tasks) >= 32:
                raise NewsRequestError("Metadata request queue is full")
            task = asyncio.create_task(self._fetch(key, url, params))
            self._tasks[key] = task
            task.add_done_callback(
                lambda done: None if done.cancelled() else done.exception()
            )
        return await asyncio.shield(task)

    async def _fetch(
        self, key: str, url: str, params: dict[str, str]
    ) -> NewsJsonSnapshot:
        try:
            async with asyncio.timeout(self._timeout):
                async with self._lock:
                    if self._clock() < self._blocked_until and self._failure:
                        raise self._failure
                    for attempt in range(2):
                        await asyncio.sleep(max(0, self._next_request - self._clock()))
                        self._next_request = self._clock() + self._interval
                        try:
                            payload = await self._read(url, params)
                            break
                        except NewsRequestError as error:
                            if (
                                attempt == 0
                                and error.http_status == 408
                                and error.retry_after_seconds is None
                            ):
                                await asyncio.sleep(1)
                                continue
                            raise
                self._cache[key] = (self._clock(), payload)
                self._cache.move_to_end(key)
                while len(self._cache) > 64:
                    self._cache.popitem(last=False)
                return payload
        except (httpx.TransportError, TimeoutError) as error:
            self._blocked_until = self._clock() + 30
            self._failure = NewsRequestError("Metadata transport failed or timed out")
            raise self._failure from error
        finally:
            self._tasks.pop(key, None)

    async def _read(self, url: str, params: dict[str, str]) -> NewsJsonSnapshot:
        async with self._client.stream(
            "GET",
            url,
            params=params,
            follow_redirects=False,
            headers={"User-Agent": "DisasterMonitorDiscovery/1.0"},
        ) as response:
            if response.status_code != 200:
                delay = _retry_after(response.headers.get("Retry-After"))
                error = NewsRequestError(
                    "Metadata provider refused or failed the request",
                    response.status_code,
                    delay,
                )
                if response.status_code == 429 or response.status_code >= 500 or delay:
                    fallback = 900 if response.status_code == 429 else 30
                    self._blocked_until = self._clock() + max(fallback, delay or 0)
                    self._failure = error
                raise error
            body = bytearray()
            async for chunk in response.aiter_bytes():
                body.extend(chunk)
                if len(body) > self._maximum_bytes:
                    raise NewsRequestError("Metadata response exceeded byte limit")
            return NewsJsonSnapshot(json.loads(body), datetime.now(UTC))

    async def aclose(self) -> None:
        tasks = tuple(self._tasks.values())
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


def _retry_after(value: str | None) -> float | None:
    if value is None:
        return None
    try:
        return max(0, float(value))
    except ValueError:
        try:
            return max(
                0, (parsedate_to_datetime(value) - datetime.now(UTC)).total_seconds()
            )
        except (ValueError, TypeError, OverflowError):
            return None
