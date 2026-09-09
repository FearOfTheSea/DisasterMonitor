"""News observations and cautiously promoted disaster candidates."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from disaster_monitor.domain.disaster_types import Disaster
from disaster_monitor.domain.evidence_types import SourceReference


def _require_aware(name: str, value: datetime | None) -> None:
    if value is not None and (value.tzinfo is None or value.utcoffset() is None):
        raise ValueError(f"{name} must be timezone-aware.")


class IncidentCandidateStatus(StrEnum):
    """Evidence state of a candidate; news alone never means verified."""

    PROVISIONAL_NEWS_DETECTED = "provisional_news_detected"
    SOURCE_BACKED = "source_backed"
    REJECTED = "rejected"


@dataclass(frozen=True, slots=True)
class NewsFeedItem:
    """Provider-neutral metadata returned by a breaking-news feed."""

    external_id: str
    publisher: str
    title: str
    canonical_url: str
    published_at: datetime
    updated_at: datetime | None

    def __post_init__(self) -> None:
        if not all(
            value.strip()
            for value in (
                self.external_id,
                self.publisher,
                self.title,
                self.canonical_url,
            )
        ):
            raise ValueError("News feed items require identity and attribution.")
        if not self.canonical_url.startswith("https://"):
            raise ValueError("News feed items require a canonical HTTPS URL.")
        _require_aware("published_at", self.published_at)
        _require_aware("updated_at", self.updated_at)


@dataclass(frozen=True, slots=True)
class NewsObservation:
    """Immutable record of when this system first received a publication."""

    observation_id: str
    source_id: str
    item: NewsFeedItem
    observed_at: datetime

    def __post_init__(self) -> None:
        if not self.observation_id.strip() or not self.source_id.strip():
            raise ValueError("News observations require stable identity.")
        _require_aware("observed_at", self.observed_at)
        if self.observed_at < self.item.published_at:
            raise ValueError("A news observation cannot precede publication.")


@dataclass(frozen=True, slots=True)
class IncidentCandidate:
    """One immutable revision of a source-attributed disaster candidate."""

    candidate_id: str
    revision_id: str
    disaster: Disaster
    location: str
    event_time: datetime
    status: IncidentCandidateStatus
    sources: tuple[SourceReference, ...]
    news_break_at: datetime
    first_observed_at: datetime
    candidate_created_at: datetime
    verified_at: datetime | None = None
    rejected_at: datetime | None = None

    def __post_init__(self) -> None:
        if not all(
            value.strip()
            for value in (self.candidate_id, self.revision_id, self.location)
        ):
            raise ValueError(
                "Incident candidates require stable identity and location."
            )
        if not self.sources:
            raise ValueError("Incident candidates require attributable news evidence.")
        for name, value in (
            ("event_time", self.event_time),
            ("news_break_at", self.news_break_at),
            ("first_observed_at", self.first_observed_at),
            ("candidate_created_at", self.candidate_created_at),
            ("verified_at", self.verified_at),
            ("rejected_at", self.rejected_at),
        ):
            _require_aware(name, value)
        if self.news_break_at > self.first_observed_at:
            raise ValueError("A candidate cannot be observed before its news break.")
        if self.first_observed_at > self.candidate_created_at:
            raise ValueError("A candidate cannot be created before first observation.")
        if (
            self.status is IncidentCandidateStatus.SOURCE_BACKED
            and self.verified_at is None
        ):
            raise ValueError("A source-backed candidate requires verified_at.")
        if self.status is IncidentCandidateStatus.REJECTED and self.rejected_at is None:
            raise ValueError("A rejected candidate requires rejected_at.")


@dataclass(frozen=True, slots=True)
class IncidentDetectionTimeline:
    """Auditable clocks used to measure the twelve-hour objective."""

    news_break_at: datetime | None = None
    first_observed_at: datetime | None = None
    candidate_created_at: datetime | None = None
    verified_at: datetime | None = None
    monitor_visible_at: datetime | None = None
    assistant_ready_at: datetime | None = None

    def __post_init__(self) -> None:
        values = (
            ("news_break_at", self.news_break_at),
            ("first_observed_at", self.first_observed_at),
            ("candidate_created_at", self.candidate_created_at),
            ("verified_at", self.verified_at),
            ("monitor_visible_at", self.monitor_visible_at),
            ("assistant_ready_at", self.assistant_ready_at),
        )
        for name, value in values:
            _require_aware(name, value)
