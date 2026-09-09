"""Bounded HTTP adapters for licensed and multilingual news metadata feeds."""

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


class LicensedJsonNewsFeed:
    """Configured licensed feed with a narrow normalized JSON contract.

    Deployments adapt AP or Reuters gateway responses to ``items`` containing
    id, publisher, title, url, published_at, and optional updated_at fields.
    Credentials and licensed content remain outside the application boundary.
    """

    def __init__(
        self,
        *,
        source_id: str,
        endpoint: str,
        token: str,
        timeout_seconds: float = 10,
        maximum_response_bytes: int = 1_000_000,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        if not endpoint.startswith("https://") or not token.strip():
            raise ValueError("Licensed news feeds require HTTPS and a credential.")
        self.source_id = source_id
        self._endpoint = endpoint
        self._token = token
        self._timeout_seconds = timeout_seconds
        self._maximum_response_bytes = maximum_response_bytes
        self._client = client

    async def fetch_since(
        self, *, since: datetime, now: datetime
    ) -> tuple[NewsFeedItem, ...]:
        _validate_window(since, now)
        payload = await _get_json(
            self._client,
            self._endpoint,
            timeout_seconds=self._timeout_seconds,
            maximum_response_bytes=self._maximum_response_bytes,
            params={
                "published_after": since.isoformat(),
                "published_before": now.isoformat(),
            },
            headers={"Authorization": f"Bearer {self._token}"},
        )
        records = payload.get("items", []) if isinstance(payload, dict) else []
        return tuple(
            item for record in records if (item := _licensed_item(record)) is not None
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


def _licensed_item(value: object) -> NewsFeedItem | None:
    if not isinstance(value, dict):
        return None
    try:
        return NewsFeedItem(
            external_id=str(value["id"]),
            publisher=str(value["publisher"]),
            title=str(value["title"]),
            canonical_url=str(value["url"]),
            published_at=_iso_datetime(value["published_at"]),
            updated_at=(
                _iso_datetime(value["updated_at"])
                if value.get("updated_at") is not None
                else None
            ),
        )
    except (KeyError, TypeError, ValueError):
        return None


def _iso_datetime(value: object) -> datetime:
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("News timestamps must include a timezone.")
    return parsed


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
    headers: dict[str, str] | None = None,
) -> object:
    if client is not None:
        response = await client.get(url, params=params, headers=headers)
        response.raise_for_status()
        return _bounded_json(response, maximum_response_bytes)
    async with httpx.AsyncClient(timeout=timeout_seconds) as temporary_client:
        response = await temporary_client.get(url, params=params, headers=headers)
        response.raise_for_status()
        return _bounded_json(response, maximum_response_bytes)


def _bounded_json(response: httpx.Response, maximum_response_bytes: int) -> object:
    if len(response.content) > maximum_response_bytes:
        raise ValueError("News feed response exceeded the configured size limit.")
    return response.json()
