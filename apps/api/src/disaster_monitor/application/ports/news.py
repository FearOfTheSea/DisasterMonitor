"""Consumer-owned ports for breaking-news sensing and candidate persistence."""

from datetime import datetime
from typing import Protocol

from disaster_monitor.domain.news import (
    IncidentCandidate,
    NewsFeedItem,
    NewsObservation,
)


class BreakingNewsFeed(Protocol):
    source_id: str

    async def fetch_since(
        self, *, since: datetime, now: datetime
    ) -> tuple[NewsFeedItem, ...]: ...


class NewsCandidateStore(Protocol):
    async def append_news_observation(self, observation: NewsObservation) -> bool: ...

    async def append_incident_candidate(self, candidate: IncidentCandidate) -> bool: ...

    async def latest_incident_candidates(
        self, *, since: datetime
    ) -> tuple[IncidentCandidate, ...]: ...
