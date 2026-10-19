"""Durable acquisition identities and evidence, independent of providers and storage."""

from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
from typing import Literal

from disaster_monitor.domain.discovery import (
    CollectionProgress,
    DiscoveryArticle,
    DiscoveryRun,
)
from disaster_monitor.domain.news import NewsFeedItem

WorkKind = Literal["search", "retrieve"]
FailureOutcome = Literal[
    "rate_limited",
    "access_refused",
    "transport_failed",
    "invalid_response",
    "article_unavailable",
    "attempts_exhausted",
    "capacity_exhausted",
]


@dataclass(frozen=True, slots=True)
class CollectionPartition:
    provider: str
    query: str
    start: datetime
    end: datetime
    cursor: str = ""
    depth: int = 0
    generation: str = "v1"
    alternate_for: str | None = None

    def __post_init__(self) -> None:
        if not self.provider.strip() or not self.query.strip():
            raise ValueError("Collection requires provider and query identities.")
        if (
            self.start.tzinfo is None
            or self.end.tzinfo is None
            or self.start >= self.end
        ):
            raise ValueError("Collection partitions require ordered aware timestamps.")
        if not 0 <= self.depth <= 12:
            raise ValueError("Collection partition depth must be bounded.")

    @property
    def key(self) -> str:
        fields = (
            self.provider,
            self.query,
            self.start.isoformat(),
            self.end.isoformat(),
            self.generation,
            self.alternate_for or "",
        )
        return sha256("|".join(fields).encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class CollectionPage:
    leads: tuple[NewsFeedItem, ...] = ()
    articles: tuple[DiscoveryArticle, ...] = ()
    next_cursor: str | None = None
    children: tuple[CollectionPartition, ...] = ()
    saturated: bool = False
    notices: tuple[str, ...] = ()
    supplemental: tuple[DiscoveryArticle, ...] = ()
    requested_start: datetime | None = None
    requested_end: datetime | None = None


@dataclass(frozen=True, slots=True)
class ClaimedCollectionWork:
    work_id: str
    token: str
    kind: WorkKind
    provider: str
    partition: CollectionPartition | None
    lead: NewsFeedItem | None
    attempts: int
    alternate_depth: int = 0


@dataclass(frozen=True, slots=True)
class CollectionSnapshot:
    run: DiscoveryRun
    articles: tuple[DiscoveryArticle, ...]
    leads: tuple[NewsFeedItem, ...]
    supplemental: tuple[DiscoveryArticle, ...]
    progress: CollectionProgress


@dataclass(slots=True)
class CollectionProviderError(Exception):
    outcome: FailureOutcome
    detail: str
    retry_after_seconds: float | None = None

    def __str__(self) -> str:
        return self.detail
