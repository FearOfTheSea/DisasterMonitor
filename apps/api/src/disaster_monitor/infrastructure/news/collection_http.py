"""One bounded provider request per durable attempt; queue time is not network time."""

import asyncio
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from time import monotonic

import httpx

from disaster_monitor.domain.collection import CollectionProviderError, FailureOutcome
from disaster_monitor.infrastructure.news.request_schedule import (
    NewsJsonSnapshot,
    _retry_after,
)


@dataclass(frozen=True, slots=True)
class CollectionHttpResponse:
    body: bytes
    retrieved_at: datetime
    status_code: int = 200


class CollectionHttp:
    def __init__(
        self,
        *,
        client: httpx.AsyncClient | None = None,
        timeout_seconds: float = 15,
        minimum_interval: float = 1,
        maximum_bytes: int = 2_000_000,
        user_agent: str = "DisasterMonitorDiscovery/1.0",
    ) -> None:
        self._client = client or httpx.AsyncClient(
            timeout=timeout_seconds, trust_env=False
        )
        self._owns_client = client is None
        self._timeout = timeout_seconds
        self._interval = minimum_interval
        self._maximum_bytes = maximum_bytes
        self._user_agent = user_agent
        self._lock = asyncio.Lock()
        self._next_request = 0.0

    async def get_json(self, url: str, params: dict[str, str]) -> NewsJsonSnapshot:
        response = await self.get_bytes(url, params)
        try:
            return NewsJsonSnapshot(json.loads(response.body), response.retrieved_at)
        except (ValueError, TypeError) as error:
            raise CollectionProviderError(
                "invalid_response", "News service returned malformed JSON."
            ) from error

    async def get_bytes(
        self,
        url: str,
        params: dict[str, str],
        *,
        accepted_statuses: tuple[int, ...] = (200,),
    ) -> CollectionHttpResponse:
        async with self._lock:
            await asyncio.sleep(max(0, self._next_request - monotonic()))
            self._next_request = monotonic() + self._interval
            try:
                async with asyncio.timeout(self._timeout):
                    async with self._client.stream(
                        "GET",
                        url,
                        params=params,
                        follow_redirects=False,
                        headers={"User-Agent": self._user_agent},
                    ) as response:
                        if response.status_code not in accepted_statuses:
                            outcome: FailureOutcome = (
                                "rate_limited"
                                if response.status_code == 429
                                else "access_refused"
                                if response.status_code in (401, 403)
                                else "transport_failed"
                                if response.status_code >= 500
                                or response.status_code == 408
                                else "invalid_response"
                            )
                            raise CollectionProviderError(
                                outcome,
                                f"News service HTTP {response.status_code}.",
                                _retry_after(response.headers.get("Retry-After")),
                            )
                        body = bytearray()
                        async for chunk in response.aiter_bytes():
                            body.extend(chunk)
                            if len(body) > self._maximum_bytes:
                                raise CollectionProviderError(
                                    "invalid_response",
                                    "News response exceeded the byte limit.",
                                )
                        return CollectionHttpResponse(
                            bytes(body), datetime.now(UTC), response.status_code
                        )
            except (httpx.TransportError, TimeoutError) as error:
                raise CollectionProviderError(
                    "transport_failed", "News service transport failed or timed out."
                ) from error

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()
