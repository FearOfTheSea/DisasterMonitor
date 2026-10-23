"""Durable acquisition identities and evidence, independent of providers and storage."""

import re
from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
from typing import Literal

from disaster_monitor.domain.discovery import (
    CollectionProgress,
    DiscoveryArticle,
    DiscoveryRun,
)
from disaster_monitor.domain.mention_extraction import extract_mentions
from disaster_monitor.domain.news import NewsFeedItem
from disaster_monitor.domain.regional_accounts import regional_fatality_account
from disaster_monitor.domain.reported_impacts import fatality_analysis_text

WorkKind = Literal["search", "retrieve"]
_FATALITY_HINT = re.compile(
    r"\b(?:kill(?:ed|s)?|dead(?:ly)?|died|dies?|drowned|deaths?|fatalities|fatal)\b",
    re.I,
)
_NO_FATALITY_HINT = re.compile(
    r"\b(?:no|zero|without)(?:\s+(?:one|people|reported|confirmed|known))*\s+"
    r"(?:deaths?|fatalities|casualties|killed|dead(?:ly)?|drowned)\b"
    r"|\bnot\s+deadly\b",
    re.I,
)


def lead_retrieval_priority(lead: NewsFeedItem) -> int:
    """Inspect fatality hints first; this never admits a claim or removes other work."""
    hint = fatality_analysis_text(
        f"{lead.title} {lead.search_title or ''} {lead.discovery_hint or ''}"
    )
    regional = regional_fatality_account(hint)
    return int(
        bool(_FATALITY_HINT.search(hint) and not _NO_FATALITY_HINT.search(hint))
        or (
            regional is not None
            and (
                regional.value not in ("0", "Unknown")
                or "scope unresolved" in regional.qualifiers
            )
        )
    )


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
        if (
            isinstance(self.priority, bool)
            or not isinstance(self.priority, int)
            or self.priority not in (0, 1)
        ):
            raise ValueError("Collection search priority must be zero or one.")

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
