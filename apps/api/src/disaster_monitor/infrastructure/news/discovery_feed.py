"""Partitioned GDELT leads enriched from public publisher article metadata."""

import asyncio
from collections import OrderedDict
from collections.abc import AsyncIterator, Callable
from datetime import UTC, datetime, timedelta
from time import monotonic
from typing import Protocol

import httpx

from disaster_monitor.domain.discovery import (
    AcquisitionAudit,
    DiscoveryArticle,
    DiscoveryBatch,
    ReportingInterval,
)
from disaster_monitor.domain.evidence_types import SourceReference
from disaster_monitor.domain.news import NewsFeedItem
from disaster_monitor.infrastructure.news.discovery_parser import (
    parse_discovery_article,
)
from disaster_monitor.infrastructure.news.feeds import (
    _gdelt_item,
    _gdelt_time,
)
from disaster_monitor.infrastructure.news.public_documents import (
    PublicDocument,
    PublicDocumentReader,
)
from disaster_monitor.infrastructure.news.request_schedule import (
    NewsRequestError,
    ScheduledNewsJson,
)

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
    async def read(self, url: str) -> str | PublicDocument: ...


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
        minimum_request_interval: float = 5.2,
        clock: Callable[[], float] = monotonic,
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
        self._clock = clock
        self._article_cache: OrderedDict[str, tuple[float, DiscoveryArticle]] = (
            OrderedDict()
        )
        self._article_tasks: dict[str, asyncio.Task[DiscoveryArticle]] = {}
        self._schedule = ScheduledNewsJson(
            self._client,
            minimum_interval=minimum_request_interval,
            timeout_seconds=timeout_seconds,
        )

    async def aclose(self) -> None:
        article_tasks = tuple(self._article_tasks.values())
        for task in article_tasks:
            task.cancel()
        await asyncio.gather(*article_tasks, return_exceptions=True)
        await self._schedule.aclose()
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
                    snapshot = await self._schedule.get(
                        self.endpoint,
                        {
                            "query": query,
                            "mode": "artlist",
                            "format": "json",
                            "sort": "datedesc",
                            "maxrecords": str(self._maximum_records),
                            "startdatetime": _gdelt_time(start),
                            "enddatetime": _gdelt_time(end),
                        },
                    )
                    payload = snapshot.payload
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
                duplicates = 0
                for index, value in enumerate(raw):
                    item = _gdelt_item(value, index)
                    if item is None:
                        invalid_leads += 1
                    if item and item.canonical_url not in seen:
                        seen.add(item.canonical_url)
                        items.append(item)
                    elif item:
                        duplicates += 1
                remaining = category_limit - category_counts[query]
                excluded = max(0, len(items) - max(0, remaining))
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
                failures = 0
                access_failures: dict[str, str] = {}
                if invalid_leads:
                    issues.append(
                        f"{invalid_leads} invalid or non-HTTPS leads excluded."
                    )
                for offset in range(0, len(items), 4):
                    results = await asyncio.gather(
                        *(self._article(item) for item in items[offset : offset + 4]),
                        return_exceptions=True,
                    )
                    for item, result in zip(
                        items[offset : offset + 4], results, strict=True
                    ):
                        if isinstance(result, BaseException):
                            failures += 1
                            access_failures[item.canonical_url] = _access_failure(
                                result
                            )
                            issues.append(
                                f"{access_failures[item.canonical_url]}; "
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
                                access_issue=access_failures.get(
                                    item.canonical_url,
                                    "Publisher content unavailable; "
                                    "article lead retained.",
                                ),
                            )
                        )
                yield DiscoveryBatch(
                    acquisition=(
                        AcquisitionAudit(
                            provider=self.source_id,
                            partition=query,
                            leads_received=len(raw),
                            invalid_leads=invalid_leads,
                            duplicate_urls=duplicates,
                            budget_excluded=excluded,
                            article_attempts=len(items),
                            article_failures=failures,
                        ),
                    ),
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
            except NewsRequestError as error:
                yield DiscoveryBatch(
                    failed_operations=1,
                    issues=(
                        f"GDELT {query}: {error}; "
                        f"{len(pending)} partitions unattempted. "
                        "Other configured discovery sources continue.",
                    ),
                )
                return
            except Exception as error:
                yield DiscoveryBatch(
                    failed_operations=1,
                    issues=(
                        f"GDELT {query}: partition failed ({type(error).__name__}).",
                    ),
                )
        if pending:
            yield DiscoveryBatch(
                truncated=True,
                issues=("GDELT query budget reached; capped partitions remain.",),
            )

    async def _article(self, item: NewsFeedItem) -> DiscoveryArticle:
        key = item.canonical_url
        cached = self._article_cache.get(key)
        if cached and self._clock() - cached[0] < 300:
            return cached[1]
        task = self._article_tasks.get(key)
        if task is None:
            task = asyncio.create_task(self._read_article(item))
            self._article_tasks[key] = task
            task.add_done_callback(
                lambda done: None if done.cancelled() else done.exception()
            )
        return await asyncio.shield(task)

    async def _read_article(self, item: NewsFeedItem) -> DiscoveryArticle:
        try:
            article = await self._parse_article(item)
            self._article_cache[item.canonical_url] = (self._clock(), article)
            self._article_cache.move_to_end(item.canonical_url)
            while len(self._article_cache) > 128:
                self._article_cache.popitem(last=False)
            return article
        finally:
            self._article_tasks.pop(item.canonical_url, None)

    async def _parse_article(self, item: NewsFeedItem) -> DiscoveryArticle:
        async with asyncio.timeout(self._timeout):
            document = await self._reader.read(item.canonical_url)
        return parse_discovery_article(
            document.html if isinstance(document, PublicDocument) else document,
            url=item.canonical_url,
            document_url=document.url if isinstance(document, PublicDocument) else None,
            title=item.title,
            publisher=item.publisher,
            retrieved_at=datetime.now(UTC),
            indexed_at=item.indexed_at,
        )


def _access_failure(error: BaseException) -> str:
    if isinstance(error, httpx.HTTPStatusError):
        return f"Publisher HTTP {error.response.status_code}: content unavailable"
    if isinstance(error, ValueError):
        return f"Publisher access rejected: {str(error)[:180]}"
    return f"Publisher transport or parsing failed ({type(error).__name__})"
