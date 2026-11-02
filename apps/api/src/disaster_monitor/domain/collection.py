"""Durable acquisition identities and evidence, independent of providers and storage."""

from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
from typing import Literal

from disaster_monitor.domain.collection_retrieval_priority import (
    lead_retrieval_priority as lead_retrieval_priority,
)
from disaster_monitor.domain.discovery import (
    CollectionProgress,
    DiscoveryArticle,
    DiscoveryRun,
)
from disaster_monitor.domain.mention_extraction import extract_mentions
from disaster_monitor.domain.news import NewsFeedItem

WorkKind = Literal["search", "retrieve"]


def fatality_hint_needs_followup(lead: NewsFeedItem, article: DiscoveryArticle) -> bool:
    """Seek other wording for an unresolved hint; never promote the hint to a claim."""
    if not lead_retrieval_priority(lead):
        return False
    mentions = extract_mentions(
        article.text,
        article.source,
        location=article.location,
        event_time=article.event_time,
        geometry=article.geometry,
    )
    return not any(
        claim.fact.category == "fatalities" and claim.fact.value not in ("0", "Unknown")
        for mention in mentions
        if mention.role in ("reported", "ongoing", "historical")
        for claim in mention.claims
    )


FailureOutcome = Literal[
    "policy_deferred",
    "rate_limited",
    "access_refused",
    "transport_failed",
    "invalid_response",
    "article_unavailable",
    "attempts_exhausted",
    "capacity_exhausted",
]


def search_acquisition_priority(
    *, alternate_for: str | None = None, defer_initial_request: bool = False
) -> int:
    """Complete initial coverage before an acquired-headline follow-up stream."""
    return int(not alternate_for and not defer_initial_request)


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
    priority: int = 0
    # Archive search identity can outlive a viewer's article refresh generation.
    retrieval_generation: str | None = None
    # Citation expansion starts after initial index coverage. Once a request has
    # supplied continuation state, finish that state at normal search priority.
    defer_initial_request: bool = False
    # Public metadata resolution can be shared by identity across query windows.
    shared_resource: bool = False

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
        if not isinstance(self.shared_resource, bool) or (
            self.shared_resource and (self.depth < 1 or self.alternate_for is not None)
        ):
            raise ValueError("Shared resources require a bounded metadata child.")
        if not isinstance(self.defer_initial_request, bool):
            raise ValueError("Initial request deferral must be boolean.")
        if (
            isinstance(self.priority, bool)
            or not isinstance(self.priority, int)
            or self.priority not in (0, 1)
        ):
            raise ValueError("Collection search priority must be zero or one.")

    @property
    def key(self) -> str:
        if self.shared_resource:
            return sha256(
                "|".join(
                    (self.provider, "shared-resource", self.query, self.generation)
                ).encode()
            ).hexdigest()
        fields = (
            self.provider,
            self.query,
            self.start.isoformat(),
            self.end.isoformat(),
            self.generation,
            self.alternate_for or "",
        )
        return sha256("|".join(fields).encode()).hexdigest()


def search_continuation_priority(partition: CollectionPartition) -> int:
    """Finish started deferred metadata without promoting ordinary follow-up pages."""
    return max(
        partition.priority,
        int(partition.defer_initial_request),
        search_acquisition_priority(alternate_for=partition.alternate_for),
    )


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
    # Policy waits remain audited attempts but do not spend the failure allowance.
    policy_deferrals: int = 0


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
