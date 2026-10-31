"""Immutable news-index observations, separate from publisher article captures."""

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from disaster_monitor.domain.news import NewsFeedItem


@dataclass(frozen=True, slots=True)
class IndexReportingSnapshot:
    page: int
    membership: int


@dataclass(frozen=True, slots=True)
class IndexReportingPosition:
    page: int
    item: int


@dataclass(frozen=True, slots=True)
class IndexedReportingObservation:
    observation_id: str
    provider: str
    observed_at: datetime
    item: NewsFeedItem


@dataclass(frozen=True, slots=True)
class IndexedReportingPage:
    observations: tuple[IndexedReportingObservation, ...]
    snapshot: IndexReportingSnapshot
    next_position: IndexReportingPosition | None


class IndexedReportingReader(Protocol):
    async def read_page(
        self,
        scan_id: str,
        *,
        query: str,
        snapshot: IndexReportingSnapshot | None,
        after: IndexReportingPosition | None,
        limit: int,
    ) -> IndexedReportingPage | None:
        """Read only this scan's observed index entries; None means no journal scan."""
        ...
