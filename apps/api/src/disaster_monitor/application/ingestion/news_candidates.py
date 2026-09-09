"""Deterministic news sensing and provisional-candidate promotion."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from disaster_monitor.application.ports.news import BreakingNewsFeed, NewsCandidateStore
from disaster_monitor.domain.disaster import Disaster, SourceAuthority, SourceReference
from disaster_monitor.domain.hazards.news_classification import (
    classify_major_disaster_headline,
)
from disaster_monitor.domain.news import (
    IncidentCandidate,
    IncidentCandidateStatus,
    NewsFeedItem,
    NewsObservation,
)


@dataclass(frozen=True, slots=True)
class NewsIngestionResult:
    observations_seen: int
    observations_inserted: int
    candidates_inserted: int


_LOCATION_PATTERNS = (
    re.compile(r"\b(?:near|in|across)\s+([^:;]+?)(?:\s+(?:as|after|amid)\b|$)", re.I),
    re.compile(
        r"\b(?:hits?|strikes?|forces evacuations near)\s+([^:;]+?)"
        r"(?:\s+(?:as|after|amid)\b|$)",
        re.I,
    ),
)
_EVENT_NOISE = frozenset(
    "a an and as after amid across forces in near of on the to wildfire fire "
    "flood flooding earthquake quake landslide mudslide hurricane typhoon "
    "cyclone tropical storm volcano "
    "eruption erupts hit hits strike strikes".split()
)
MAJOR_NEWS_PUBLISHERS_V1 = frozenset(
    {
        "associated press",
        "apnews.com",
        "reuters",
        "reuters.com",
        "bbc",
        "bbc.com",
        "bbc.co.uk",
        "aljazeera.com",
        "cnn.com",
        "dw.com",
        "france24.com",
        "theguardian.com",
    }
)


class NewsCandidateIngestion:
    """Persist every observation and promote only recognized hazards."""

    def __init__(
        self,
        feed: BreakingNewsFeed,
        store: NewsCandidateStore,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        lookback: timedelta = timedelta(minutes=30),
        major_publishers: frozenset[str] = MAJOR_NEWS_PUBLISHERS_V1,
    ) -> None:
        self._feed = feed
        self._store = store
        self._clock = clock
        self._lookback = lookback
        self._major_publishers = frozenset(
            publisher.casefold() for publisher in major_publishers
        )

    async def refresh(self) -> NewsIngestionResult:
        now = self._clock()
        items = await self._feed.fetch_since(since=now - self._lookback, now=now)
        observations_inserted = 0
        candidates_inserted = 0
        for item in items:
            observation = _observation(self._feed.source_id, item, now)
            if not await self._store.append_news_observation(observation):
                continue
            observations_inserted += 1
            if not _is_major_publisher(item.publisher, self._major_publishers):
                continue
            disaster = classify_major_disaster_headline(item.title)
            if disaster is None:
                continue
            candidate = await self._candidate(observation, disaster)
            candidates_inserted += int(
                await self._store.append_incident_candidate(candidate)
            )
        return NewsIngestionResult(
            observations_seen=len(items),
            observations_inserted=observations_inserted,
            candidates_inserted=candidates_inserted,
        )

    async def _candidate(
        self, observation: NewsObservation, disaster: Disaster
    ) -> IncidentCandidate:
        item = observation.item
        location = _location(item.title)
        candidate_id = _candidate_id(
            disaster, location, item.title, published_at=item.published_at
        )
        existing = {
            candidate.candidate_id: candidate
            for candidate in await self._store.latest_incident_candidates(
                since=item.published_at - timedelta(days=3)
            )
        }.get(candidate_id)
        source = SourceReference(
            source_id=observation.source_id,
            publisher=item.publisher,
            title=item.title,
            canonical_url=item.canonical_url,
            published_at=item.published_at,
            updated_at=item.updated_at,
            retrieved_at=observation.observed_at,
            authority=SourceAuthority.SECONDARY,
        )
        sources = tuple(
            sorted(
                {
                    entry.source_id: entry for entry in (*existing.sources, source)
                }.values()
                if existing is not None
                else (source,),
                key=lambda entry: (
                    entry.published_at or entry.retrieved_at,
                    entry.source_id,
                ),
            )
        )
        news_break_at = min(
            source_item.published_at or source_item.retrieved_at
            for source_item in sources
        )
        first_observed_at = min(source_item.retrieved_at for source_item in sources)
        revision_material = "|".join(
            source_item.source_id + source_item.canonical_url for source_item in sources
        )
        return IncidentCandidate(
            candidate_id=candidate_id,
            revision_id=f"{candidate_id}:{hashlib.sha256(revision_material.encode()).hexdigest()[:16]}",
            disaster=disaster,
            location=location,
            event_time=news_break_at,
            status=IncidentCandidateStatus.PROVISIONAL_NEWS_DETECTED,
            sources=sources,
            news_break_at=news_break_at,
            first_observed_at=first_observed_at,
            candidate_created_at=observation.observed_at,
        )


def _observation(
    source_id: str, item: NewsFeedItem, observed_at: datetime
) -> NewsObservation:
    identity = hashlib.sha256(
        f"{source_id}|{item.external_id}|{item.canonical_url}".encode()
    ).hexdigest()
    return NewsObservation(
        observation_id=f"news:{identity[:32]}",
        source_id=source_id,
        item=item,
        observed_at=observed_at,
    )


def _location(title: str) -> str:
    for pattern in _LOCATION_PATTERNS:
        match = pattern.search(title)
        if match:
            value = match.group(1).strip(" .,-")
            if value:
                return value
    return title.strip()


def _candidate_id(
    disaster: Disaster, location: str, title: str, *, published_at: datetime
) -> str:
    identity_text = location if location != title.strip() else title
    tokens = re.findall(r"[a-z0-9]+", identity_text.casefold())
    signature = " ".join(sorted(set(tokens) - _EVENT_NOISE))
    day = published_at.astimezone(UTC).date().isoformat()
    digest = hashlib.sha256(f"{disaster.value}|{signature}|{day}".encode()).hexdigest()[
        :24
    ]
    return f"news-candidate:{digest}"


def _is_major_publisher(publisher: str, allowlist: frozenset[str]) -> bool:
    normalized = publisher.casefold().removeprefix("www.")
    return normalized in allowlist or any(
        normalized.endswith(f".{allowed}") for allowed in allowlist if "." in allowed
    )
