"""Consumer-owned seams for resumable discovery, acquisition and article retrieval."""

from datetime import datetime
from typing import Protocol

from disaster_monitor.application.ports.discovery import DiscoveryStore
from disaster_monitor.domain.collection import (
    ClaimedCollectionWork,
    CollectionPage,
    CollectionPartition,
    CollectionSnapshot,
    FailureOutcome,
    WorkKind,
)
from disaster_monitor.domain.discovery import DiscoveryArticle, DiscoveryRun
from disaster_monitor.domain.news import NewsFeedItem


class CollectionProvider(Protocol):
    source_id: str
    queries: tuple[str, ...]
    supports_alternates: bool

    async def fetch_page(self, partition: CollectionPartition) -> CollectionPage: ...


class CollectionArticleReader(Protocol):
    async def retrieve(self, lead: NewsFeedItem) -> DiscoveryArticle: ...


class CollectionJournal(DiscoveryStore, Protocol):
    async def attach(
        self,
        run: DiscoveryRun,
        partitions: tuple[CollectionPartition, ...],
        *,
        now: datetime,
        budget: int,
    ) -> None: ...

    async def continue_scan(
        self, scan_id: str, *, now: datetime, budget: int
    ) -> None: ...

    async def claim(
        self, kind: WorkKind, worker: str, *, now: datetime, provider: str | None = None
    ) -> ClaimedCollectionWork | None: ...

    async def commit_page(
        self, work: ClaimedCollectionWork, page: CollectionPage, *, now: datetime
    ) -> bool: ...

    async def commit_article(
        self, work: ClaimedCollectionWork, article: DiscoveryArticle, *, now: datetime
    ) -> bool: ...

    async def fail(
        self,
        work: ClaimedCollectionWork,
        *,
        outcome: FailureOutcome,
        detail: str,
        now: datetime,
        retry_at: datetime | None = None,
        alternates: tuple[CollectionPartition, ...] = (),
    ) -> bool: ...

    async def snapshot(self, scan_id: str) -> CollectionSnapshot: ...

    async def finish_pass(self, *, now: datetime) -> None: ...

    async def active_scans(self) -> tuple[str, ...]: ...

    async def next_retry(self, *, now: datetime) -> datetime | None: ...


class CollectionRuntime(Protocol):
    async def start(self, days: int = 7) -> DiscoveryRun: ...
    async def get(self, scan_id: str) -> DiscoveryRun: ...
    async def continue_collection(self, scan_id: str) -> DiscoveryRun: ...
    async def wait(self, scan_id: str) -> None: ...
    async def recover(self) -> None: ...
    async def aclose(self) -> None: ...
