"""Bounded HTTP adapter for multilingual public news metadata."""

from __future__ import annotations

from datetime import UTC, datetime

import httpx

from disaster_monitor.domain.news import NewsFeedItem

_DISASTER_QUERY = (
    "(earthquake OR flood OR wildfire OR landslide OR hurricane OR typhoon OR cyclone "
    'OR "volcanic eruption") '
    "(major OR emergency OR evacuation OR killed OR deaths OR missing OR thousands)"
)


class GdeltDocNewsFeed:
    """Discover multilingual disaster reporting through GDELT DOC 2.0."""

    source_id = "gdelt-news"
    endpoint = "https://api.gdeltproject.org/api/v2/doc/doc"

    def __init__(
        self,
        *,
        timeout_seconds: float = 10,
        maximum_records: int = 100,
        maximum_response_bytes: int = 1_000_000,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._timeout_seconds = timeout_seconds
        self._maximum_records = maximum_records
        self._maximum_response_bytes = maximum_response_bytes
        self._client = client

    async def fetch_since(
        self, *, since: datetime, now: datetime
    ) -> tuple[NewsFeedItem, ...]:
        _validate_window(since, now)
        parameters = {
            "query": _DISASTER_QUERY,
            "mode": "artlist",
            "format": "json",
            "maxrecords": str(self._maximum_records),
            "sort": "datedesc",
            "startdatetime": _gdelt_time(since),
            "enddatetime": _gdelt_time(now),
        }
        payload = await _get_json(
            self._client,
            self.endpoint,
            timeout_seconds=self._timeout_seconds,
            maximum_response_bytes=self._maximum_response_bytes,
            params=parameters,
        )
        articles = payload.get("articles", []) if isinstance(payload, dict) else []
        return tuple(
            item
            for index, article in enumerate(articles)
            if (item := _gdelt_item(article, index)) is not None
        )


def _gdelt_item(value: object, index: int) -> NewsFeedItem | None:
    if not isinstance(value, dict):
        return None
    url = value.get("url")
    title = value.get("title")
    seen = _parse_gdelt_datetime(value.get("seendate"))
    if (
        not isinstance(url, str)
        or not url.startswith("https://")
        or not isinstance(title, str)
        or seen is None
    ):
        return None
    domain = value.get("domain")
    publisher = (
        domain
        if isinstance(domain, str) and domain.strip()
        else "GDELT indexed publisher"
    )
    return NewsFeedItem(
        external_id=str(value.get("url_mobile") or url or index),
        publisher=publisher,
        title=title,
        canonical_url=url,
        published_at=seen,
        updated_at=None,
    )


def _parse_gdelt_datetime(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    for pattern in ("%Y%m%dT%H%M%SZ", "%Y%m%d%H%M%S"):
        try:
            return datetime.strptime(value, pattern).replace(tzinfo=UTC)
        except ValueError:
            pass
    return None


def _gdelt_time(value: datetime) -> str:
    return value.astimezone(UTC).strftime("%Y%m%d%H%M%S")


def _validate_window(since: datetime, now: datetime) -> None:
    if since.tzinfo is None or now.tzinfo is None or since > now:
        raise ValueError("News feed windows require ordered timezone-aware times.")


async def _get_json(
    client: httpx.AsyncClient | None,
    url: str,
    *,
    timeout_seconds: float,
    maximum_response_bytes: int,
    params: dict[str, str],
) -> object:
    if client is not None:
        response = await client.get(url, params=params)
        response.raise_for_status()
        return _bounded_json(response, maximum_response_bytes)
    async with httpx.AsyncClient(timeout=timeout_seconds) as temporary_client:
        response = await temporary_client.get(url, params=params)
        response.raise_for_status()
        return _bounded_json(response, maximum_response_bytes)


def _bounded_json(response: httpx.Response, maximum_response_bytes: int) -> object:
    if len(response.content) > maximum_response_bytes:
        raise ValueError("News feed response exceeded the configured size limit.")
    return response.json()
