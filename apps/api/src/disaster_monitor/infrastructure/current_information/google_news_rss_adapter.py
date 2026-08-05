"""Google News RSS adapter for recent disaster-report discovery."""

import html
import re
from collections.abc import Callable
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from urllib.parse import urlparse
from xml.etree import ElementTree

import httpx

from disaster_monitor.application.dto import (
    DisasterInformationItem,
    DisasterInformationResult,
)
from disaster_monitor.domain.errors import DisasterInformationRuntimeError

_TAGS = re.compile(r"<[^>]+>")
_WHITESPACE = re.compile(r"\s+")


def _utc_now() -> datetime:
    return datetime.now(UTC)


class GoogleNewsRssDisasterInformationAdapter:
    """Retrieve recent report metadata without requiring an API key."""

    def __init__(
        self,
        base_url: str = "https://news.google.com/rss/search",
        timeout_seconds: float = 10.0,
        max_items: int = 8,
        lookback_days: int = 30,
        client: httpx.AsyncClient | None = None,
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        self._base_url = base_url
        self._max_items = max_items
        self._lookback_days = lookback_days
        self._clock = clock
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            timeout=timeout_seconds,
            headers={"User-Agent": "DisasterMonitor/0.1"},
        )

    async def search(self, query: str) -> DisasterInformationResult:
        """Return parsed, deduplicated RSS items ordered by publication time."""
        search_query = f"{query} when:{self._lookback_days}d"
        try:
            response = await self._client.get(
                self._base_url,
                params={
                    "q": search_query,
                    "hl": "en-US",
                    "gl": "US",
                    "ceid": "US:en",
                },
            )
            response.raise_for_status()
            root = ElementTree.fromstring(response.content)
        except (httpx.HTTPError, ElementTree.ParseError) as error:
            raise DisasterInformationRuntimeError(
                "Current disaster reports could not be retrieved."
            ) from error

        items: list[DisasterInformationItem] = []
        seen: set[tuple[str, str]] = set()
        for node in root.findall("./channel/item"):
            title = _clean_text(node.findtext("title", default=""))
            link = _clean_text(node.findtext("link", default=""))
            source_node = node.find("source")
            source = _clean_text(
                source_node.text if source_node is not None and source_node.text else ""
            )
            summary = _clean_text(node.findtext("description", default=""))
            published_at = _parse_published_at(node.findtext("pubDate", default=""))
            if not title or not source or not _is_http_url(link):
                continue
            key = (title.casefold(), source.casefold())
            if key in seen:
                continue
            seen.add(key)
            items.append(
                DisasterInformationItem(
                    title=title,
                    source=source,
                    published_at=published_at,
                    url=link,
                    summary=summary,
                )
            )

        items.sort(
            key=lambda item: item.published_at or datetime.min.replace(tzinfo=UTC),
            reverse=True,
        )
        return DisasterInformationResult(
            query=query,
            retrieved_at=self._clock().astimezone(UTC),
            items=tuple(items[: self._max_items]),
        )

    async def aclose(self) -> None:
        """Close the internally owned HTTP client."""
        if self._owns_client:
            await self._client.aclose()


def _clean_text(value: str) -> str:
    without_tags = _TAGS.sub(" ", html.unescape(value))
    return _WHITESPACE.sub(" ", without_tags).strip()


def _parse_published_at(value: str) -> datetime | None:
    if not value:
        return None
    try:
        parsed = parsedate_to_datetime(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _is_http_url(value: str) -> bool:
    return urlparse(value).scheme in {"http", "https"}
