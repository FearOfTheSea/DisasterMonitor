"""Partitioned GDELT leads enriched from public publisher article metadata."""

import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Protocol

import httpx

from disaster_monitor.domain.discovery import (
    DiscoveryArticle,
    DiscoveryBatch,
    ReportingInterval,
)
from disaster_monitor.domain.evidence_types import SourceReference
from disaster_monitor.infrastructure.news.discovery_parser import (
    parse_discovery_article,
)
from disaster_monitor.infrastructure.news.feeds import (
    _gdelt_item,
    _gdelt_time,
    _get_json,
)
from disaster_monitor.infrastructure.news.public_documents import PublicDocumentReader

_QUERIES = (
    "earthquake",
    "flood",
    "wildfire",
    "landslide",
    "drought",
    "(hurricane OR typhoon OR cyclone)",
    '("volcanic eruption" OR "volcano erupts")',
)


class ArticleReader(Protocol):
    async def read(self, url: str) -> str: ...


class GdeltDiscoveryFeed:
    source_id = "gdelt-discovery"
    endpoint = "https://api.gdeltproject.org/api/v2/doc/doc"

    def __init__(
        self,
        *,
        client: httpx.AsyncClient | None = None,
        reader: ArticleReader | None = None,
        maximum_records: int = 100,
        maximum_queries: int = 35,
        maximum_articles: int = 400,
        timeout_seconds: float = 15,
    ) -> None:
        self._client = client or httpx.AsyncClient(
            timeout=timeout_seconds, trust_env=False
        )
        self._owns_client = client is None
        self._reader = reader or PublicDocumentReader(timeout_seconds=timeout_seconds)
        self._maximum_records = maximum_records
        self._maximum_queries = maximum_queries
        self._maximum_articles = maximum_articles
        self._timeout = timeout_seconds

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def discover(
        self, *, interval: ReportingInterval
    ) -> AsyncIterator[DiscoveryBatch]:
        # Breadth first: every category gets an initial query before splitting caps.
        pending = [(query, interval.start, interval.end) for query in _QUERIES]
        calls = 0
        seen: set[str] = set()
        category_counts = dict.fromkeys(_QUERIES, 0)
        category_limit = max(1, self._maximum_articles // len(_QUERIES))
        while pending and calls < self._maximum_queries:
            query, start, end = pending.pop(0)
            calls += 1
            try:
                async with asyncio.timeout(self._timeout):
                    payload = await _get_json(
                        self._client,
                        self.endpoint,
                        timeout_seconds=self._timeout,
                        maximum_response_bytes=1_000_000,
                        params={
                            "query": query,
                            "mode": "artlist",
                            "format": "json",
                            "sort": "datedesc",
                            "maxrecords": str(self._maximum_records),
                            "startdatetime": _gdelt_time(start),
                            "enddatetime": _gdelt_time(end),
                        },
                    )
                if not isinstance(payload, dict) or not isinstance(
                    payload.get("articles"), list
                ):
                    raise ValueError("Invalid GDELT response")
                raw = payload["articles"]
                capped = len(raw) >= self._maximum_records
                can_split = end - start >= timedelta(minutes=30)
                if capped and can_split:
                    middle = start + (end - start) / 2
                    pending.extend(((query, start, middle), (query, middle, end)))
                items = []
                invalid_leads = 0
                for index, value in enumerate(raw):
                    item = _gdelt_item(value, index)
                    if item is None:
                        invalid_leads += 1
                    if item and item.canonical_url not in seen:
                        seen.add(item.canonical_url)
                        items.append(item)
                remaining = category_limit - category_counts[query]
                limited = len(items) > max(0, remaining)
                items = items[: max(0, remaining)]
                category_counts[query] += len(items)
                budget_truncated = category_counts[query] >= category_limit and any(
                    entry[0] == query for entry in pending
                )
                if category_counts[query] >= category_limit:
                    pending = [entry for entry in pending if entry[0] != query]
                # Four publisher requests at a time; every request has a wall timeout.
                articles: list[DiscoveryArticle] = []
                issues: list[str] = []
                if invalid_leads:
                    issues.append(
                        f"{invalid_leads} invalid or non-HTTPS leads excluded."
                    )
                for offset in range(0, len(items), 4):
                    results = await asyncio.gather(
                        *(self._article(item) for item in items[offset : offset + 4]),
                        return_exceptions=True,
                    )
                    for result in results:
                        if isinstance(result, BaseException):
                            issues.append(
                                "Publisher content unavailable or access rejected; "
                                "lead retained with unknown publication time."
                            )
                        else:
                            articles.append(result)
                retrieved = {a.source.canonical_url for a in articles}
                for item in items:
                    if item.canonical_url not in retrieved:
                        articles.append(
                            DiscoveryArticle(
                                source=SourceReference(
                                    source_id=self.source_id,
                                    publisher=item.publisher,
                                    title=item.title,
                                    canonical_url=item.canonical_url,
                                    published_at=None,
                                    updated_at=None,
                                    retrieved_at=datetime.now(UTC),
                                ),
                                text="",
                                indexed_at=item.indexed_at,
                                access_issue=(
                                    "Publisher content unavailable or restricted; "
                                    "article lead retained."
                                ),
                            )
                        )
                yield DiscoveryBatch(
                    articles=tuple(articles),
                    issues=tuple(
                        dict.fromkeys(
                            (
                                *issues,
                                *(
                                    (
                                        f"{query}: article budget reached; "
                                        "remaining leads uncollected.",
                                    )
                                    if limited or budget_truncated
                                    else ()
                                ),
                            )
                        )
                    ),
                    successful_operations=1,
                    truncated=limited or budget_truncated or (capped and not can_split),
                )
            except Exception:
                yield DiscoveryBatch(
                    failed_operations=1,
                    issues=(f"GDELT {query}: partition failed or timed out.",),
                )
        if pending:
            yield DiscoveryBatch(
                truncated=True,
                issues=("GDELT query budget reached; capped partitions remain.",),
            )

    async def _article(self, item: object) -> DiscoveryArticle:
        from disaster_monitor.domain.news import NewsFeedItem

        assert isinstance(item, NewsFeedItem)
        async with asyncio.timeout(self._timeout):
            html = await self._reader.read(item.canonical_url)
        return parse_discovery_article(
            html,
            url=item.canonical_url,
            title=item.title,
            publisher=item.publisher,
            retrieved_at=datetime.now(UTC),
            indexed_at=item.indexed_at,
        )
