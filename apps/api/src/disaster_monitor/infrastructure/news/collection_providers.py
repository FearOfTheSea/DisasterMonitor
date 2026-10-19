"""GDELT lead discovery and complementary ReliefWeb report pages."""

import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import httpx

from disaster_monitor.domain.collection import (
    CollectionPage,
    CollectionPartition,
    CollectionProviderError,
)
from disaster_monitor.domain.discovery import DiscoveryArticle
from disaster_monitor.domain.news import NewsFeedItem
from disaster_monitor.infrastructure.news.collection_http import CollectionJsonHttp
from disaster_monitor.infrastructure.news.discovery_feed import _QUERIES, ArticleReader
from disaster_monitor.infrastructure.news.discovery_parser import (
    parse_discovery_article,
)
from disaster_monitor.infrastructure.news.feeds import _gdelt_item, _gdelt_time
from disaster_monitor.infrastructure.news.public_documents import PublicDocumentReader
from disaster_monitor.infrastructure.news.reliefweb_discovery import (
    _CATEGORIES,
    _FIELDS,
    _article,
)


class GdeltCollectionProvider:
    source_id = "gdelt-discovery"
    supports_alternates = True
    queries = _QUERIES
    endpoint = "https://api.gdeltproject.org/api/v2/doc/doc"

    def __init__(
        self,
        *,
        client: httpx.AsyncClient | None = None,
        limit: int = 100,
        timeout_seconds: float = 15,
        minimum_interval: float = 5.2,
    ) -> None:
        self._http = CollectionJsonHttp(
            client=client,
            timeout_seconds=timeout_seconds,
            minimum_interval=minimum_interval,
        )
        self._limit = limit

    async def fetch_page(self, partition: CollectionPartition) -> CollectionPage:
        requested_end = min(partition.end, datetime.now(UTC))
        snapshot = await self._http.get(
            self.endpoint,
            {
                "query": partition.query,
                "mode": "artlist",
                "format": "json",
                "sort": "datedesc",
                "maxrecords": str(self._limit),
                "startdatetime": _gdelt_time(partition.start),
                "enddatetime": _gdelt_time(requested_end),
            },
        )
        payload = snapshot.payload
        if not isinstance(payload, dict) or not isinstance(
            payload.get("articles"), list
        ):
            raise CollectionProviderError(
                "invalid_response", "GDELT returned no valid article list."
            )
        raw = payload["articles"]
        leads = tuple(
            item
            for index, value in enumerate(raw)
            if (item := _gdelt_item(value, index))
        )
        capped = len(raw) >= self._limit
        can_split = (
            capped
            and not partition.alternate_for
            and partition.depth < 12
            and requested_end - partition.start >= timedelta(minutes=30)
        )
        children: tuple[CollectionPartition, ...] = ()
        if can_split:
            middle = partition.start + (requested_end - partition.start) / 2
            children = (
                replace(partition, end=middle, cursor="", depth=partition.depth + 1),
                replace(
                    partition,
                    start=middle,
                    end=requested_end,
                    cursor="",
                    depth=partition.depth + 1,
                ),
            )
        invalid = len(raw) - len(leads)
        return CollectionPage(
            requested_start=partition.start,
            requested_end=requested_end,
            leads=leads,
            children=children,
            saturated=capped and not can_split,
            notices=(f"GDELT excluded {invalid} invalid leads.",) if invalid else (),
        )

    async def aclose(self) -> None:
        await self._http.aclose()


class ReliefWebCollectionProvider:
    source_id = "reliefweb-discovery"
    supports_alternates = False
    queries = _CATEGORIES
    endpoint = "https://api.reliefweb.int/v2/reports"

    def __init__(
        self,
        *,
        app_name: str | None,
        client: httpx.AsyncClient | None = None,
        limit: int = 20,
        timeout_seconds: float = 15,
        minimum_interval: float = 1,
    ) -> None:
        self._app_name = (app_name or "").strip()
        self._limit = limit
        self._http = CollectionJsonHttp(
            client=client,
            timeout_seconds=timeout_seconds,
            minimum_interval=minimum_interval,
        )

    async def fetch_page(self, partition: CollectionPartition) -> CollectionPage:
        if not self._app_name or self._app_name.lower() in {
            "disaster-monitor-local",
            "change-me",
            "your-app-name",
        }:
            raise CollectionProviderError(
                "access_refused", "ReliefWeb needs an approved configured appname."
            )
        offset = int(partition.cursor or "0")
        params = {
            "appname": self._app_name,
            "filter[operator]": "AND",
            "filter[conditions][0][field]": "disaster_type.name",
            "filter[conditions][0][value]": partition.query,
            "filter[conditions][1][field]": "date.original",
            "filter[conditions][1][value][from]": partition.start.isoformat(
                timespec="seconds"
            ),
            "filter[conditions][1][value][to]": partition.end.isoformat(
                timespec="seconds"
            ),
            "sort[]": "date.original:desc",
            "limit": str(self._limit),
            "offset": str(offset),
            **{f"fields[include][{i}]": field for i, field in enumerate(_FIELDS)},
        }
        snapshot = await self._http.get(self.endpoint, params)
        payload = snapshot.payload
        if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
            raise CollectionProviderError(
                "invalid_response", "ReliefWeb returned no valid report list."
            )
        raw = payload["data"]
        articles = tuple(
            article
            for value in raw
            if (article := _article(value, retrieved_at=snapshot.retrieved_at))
        )
        total = payload.get("totalCount")
        has_more = (
            total > offset + self._limit
            if isinstance(total, int)
            else len(raw) >= self._limit
        )
        invalid = len(raw) - len(articles)
        return CollectionPage(
            requested_start=partition.start,
            requested_end=partition.end,
            articles=articles,
            next_cursor=str(offset + self._limit) if has_more else None,
            notices=(f"ReliefWeb excluded {invalid} malformed reports.",)
            if invalid
            else (),
        )

    async def aclose(self) -> None:
        await self._http.aclose()


class PublicCollectionArticleReader:
    def __init__(
        self, *, reader: ArticleReader | None = None, timeout_seconds: float = 15
    ) -> None:
        self._reader = reader or PublicDocumentReader(timeout_seconds=timeout_seconds)
        self._timeout = timeout_seconds

    async def retrieve(self, lead: NewsFeedItem) -> DiscoveryArticle:
        try:
            async with asyncio.timeout(self._timeout):
                html = await self._reader.read(lead.canonical_url)
        except httpx.HTTPStatusError as error:
            raise CollectionProviderError(
                "article_unavailable",
                f"Publisher HTTP {error.response.status_code}; "
                "article access unavailable.",
            ) from error
        except ValueError as error:
            raise CollectionProviderError(
                "article_unavailable", str(error)[:200]
            ) from error
        # Publisher metadata establishes publication; provider age stays separate.
        return parse_discovery_article(
            html,
            url=lead.canonical_url,
            title=lead.title,
            publisher=lead.publisher,
            retrieved_at=datetime.now(UTC),
            indexed_at=lead.indexed_at,
        )
