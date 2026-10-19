"""Publication-window discovery, attributed claims, and conservative association."""

import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal

from disaster_monitor.domain.disaster_types import Disaster
from disaster_monitor.domain.discovery_claim_scope import scoped_disaster_text
from disaster_monitor.domain.event_mentions import EventMention
from disaster_monitor.domain.events import EventGeometry
from disaster_monitor.domain.evidence_types import SourceReference
from disaster_monitor.domain.hazards.news_classification import classify_disaster_text


@dataclass(frozen=True, slots=True)
class ReportingInterval:
    days: int
    start: datetime
    end: datetime

    def __post_init__(self) -> None:
        if (
            isinstance(self.days, bool)
            or not isinstance(self.days, int)
            or self.days not in (1, 3, 7, 14, 30)
        ):
            raise ValueError("Reporting period must be 1, 3, 7, 14, or 30 days.")
        if self.start.tzinfo is None or self.end.tzinfo is None:
            raise ValueError("Reporting interval requires timezone-aware times.")
        if self.end - self.start != timedelta(days=self.days):
            raise ValueError("Reporting interval must be a fixed rolling duration.")

    @classmethod
    def at_start(cls, days: int, now: datetime) -> "ReportingInterval":
        return cls(days, now - timedelta(days=days), now)


@dataclass(frozen=True, slots=True)
class DiscoveryArticle:
    source: SourceReference
    text: str
    indexed_at: datetime | None = None
    event_time: datetime | None = None
    location: str | None = None
    geometry: EventGeometry | None = None
    event_key: str | None = None
    origin: str | None = None
    access_issue: str | None = None
    original_url: str | None = None

    def __post_init__(self) -> None:
        for value in (
            self.source.published_at,
            self.source.updated_at,
            self.source.retrieved_at,
            self.indexed_at,
            self.event_time,
        ):
            if value is not None and (
                value.tzinfo is None or value.utcoffset() is None
            ):
                raise ValueError("Discovery timestamps must be timezone-aware.")


@dataclass(frozen=True, slots=True)
class AssessedReport:
    article: DiscoveryArticle
    disaster: Disaster | None
    eligibility: Literal[
        "eligible",
        "unknown_publication",
        "outside_interval",
        "unclassified",
        "uncertain_publication",
    ]
    fatality_evidence: tuple[str, ...]
    mentions: tuple[EventMention, ...] = ()
    mention: EventMention | None = None
    # Physical occurrence mentions in the article, excluding response/forecast context.
    mention_count: int = 0


@dataclass(frozen=True, slots=True)
class DiscoveryEvent:
    event_id: str
    disaster: Disaster
    location: str
    event_time: datetime | None
    geometry: EventGeometry | None
    reports: tuple[AssessedReport, ...]
    independent_origins: int
    supplemental_sources: tuple[SourceReference, ...] = ()
    collection_notices: tuple[str, ...] = ()
    identity_status: Literal["candidate", "associated"] = "candidate"
    association_reasons: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class AcquisitionAudit:
    provider: str
    partition: str
    leads_received: int = 0
    invalid_leads: int = 0
    duplicate_urls: int = 0
    budget_excluded: int = 0
    article_attempts: int = 0
    article_failures: int = 0


@dataclass(frozen=True, slots=True)
class DiscoveryBatch:
    articles: tuple[DiscoveryArticle, ...] = ()
    issues: tuple[str, ...] = ()
    successful_operations: int = 0
    failed_operations: int = 0
    truncated: bool = False
    supplemental: tuple[DiscoveryArticle, ...] = ()
    acquisition: tuple[AcquisitionAudit, ...] = ()


@dataclass(frozen=True, slots=True)
class DiscoveryRun:
    scan_id: str
    interval: ReportingInterval
    status: Literal["running", "completed", "incomplete", "failed"] = "running"
    reports: tuple[AssessedReport, ...] = ()
    events: tuple[DiscoveryEvent, ...] = ()
    issues: tuple[str, ...] = ()
    successful_operations: int = 0
    failed_operations: int = 0
    truncated: bool = False
    finished_at: datetime | None = None
    supplemental: tuple[DiscoveryArticle, ...] = ()
    acquisition: tuple[AcquisitionAudit, ...] = ()
    reprocessed_from: str | None = None


# Provisional extraction: retain attributed affirmative sentences, never infer deaths
# from severity words or add figures across accounts. This is a claim, not verification.
_FATALITY = re.compile(
    r"\b(?:[1-9]\d*|one|two|three|four|five|six|seven|eight|nine|ten|"
    r"dozens|hundreds|thousands|a person|a man|a woman|a child)\b"
    r"[^.!?]{0,65}\b(?:died|dead|killed|deaths?|fatalities)\b|"
    r"\b(?:killed|claimed the lives of)\s+(?:at least\s+)?"
    r"(?:[1-9]\d*|one|two|three|four|five|six|seven|eight|nine|ten)\b",
    re.I,
)
_NEGATED = re.compile(
    r"\b(?:no|not|zero|denied|false|unconfirmed|anniversary|years? ago)\b", re.I
)


def assess_article(
    article: DiscoveryArticle,
    interval: ReportingInterval,
    *,
    country_names: frozenset[str] = frozenset(),
) -> AssessedReport:
    from disaster_monitor.domain.mention_extraction import extract_mentions

    mentions = extract_mentions(
        article.text,
        article.source,
        location=article.location,
        event_time=article.event_time,
        geometry=article.geometry,
        country_names=country_names,
    )
    disaster = classify_disaster_text(article.source.title) or classify_disaster_text(
        article.text
    )
    publication = article.source.published_at
    eligibility: Literal[
        "eligible",
        "unknown_publication",
        "outside_interval",
        "unclassified",
        "uncertain_publication",
    ] = "eligible"
    if publication is None or article.source.publication_precision == "unknown":
        eligibility = "unknown_publication"
    elif article.source.publication_precision == "day":
        day = publication.astimezone(UTC).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        end = day + timedelta(days=1)
        if day > interval.end or end <= interval.start:
            eligibility = "outside_interval"
        elif not (interval.start <= day and end <= interval.end):
            eligibility = "uncertain_publication"
        elif not mentions:
            eligibility = "unclassified"
    elif not interval.start <= publication <= interval.end:
        eligibility = "outside_interval"
    elif not mentions:
        eligibility = "unclassified"
    return AssessedReport(
        article,
        disaster,
        eligibility,
        fatality_accounts(article, disaster),
        mentions,
        mention_count=sum(m.role in ("reported", "ongoing") for m in mentions),
    )


def fatality_accounts(
    article: DiscoveryArticle, disaster: Disaster | None
) -> tuple[str, ...]:
    """Project current source-scoping policy, including for older retained scans."""
    return tuple(
        sentence.strip()[:600]
        for sentence in re.split(
            r"(?<=[.!?])\s+",
            scoped_disaster_text(article.text, article.source.title, disaster),
        )
        if _FATALITY.search(sentence) and not _NEGATED.search(sentence)
    )[:10]


def group_reports(
    reports: tuple[AssessedReport, ...], previous: tuple[DiscoveryEvent, ...] = ()
) -> tuple[DiscoveryEvent, ...]:
    from disaster_monitor.domain.event_association import associate_mentions

    return associate_mentions(reports, previous)


def supplement_events(
    events: tuple[DiscoveryEvent, ...], catalog: tuple[DiscoveryArticle, ...]
) -> tuple[DiscoveryEvent, ...]:
    """Attach catalog geometry only with explicit identity or precise place/time."""
    from dataclasses import replace

    catalogs: dict[Disaster, list[DiscoveryArticle]] = {}
    for item in catalog:
        hazard = classify_disaster_text(item.source.title)
        if hazard is not None:
            catalogs.setdefault(hazard, []).append(item)
    result = []
    for event in events:
        matches = [
            item
            for item in catalogs.get(event.disaster, ())
            if any(
                (
                    report.article.event_key
                    and report.article.event_key == item.event_key
                )
                or (
                    report.article.location
                    and item.location
                    and report.article.location.casefold() == item.location.casefold()
                    and report.article.event_time
                    and item.event_time
                    and abs(
                        (report.article.event_time - item.event_time).total_seconds()
                    )
                    <= 3600
                )
                for report in event.reports
            )
        ]
        if len(matches) == 1:
            item = matches[0]
            event = replace(
                event,
                geometry=event.geometry or item.geometry,
                event_time=event.event_time or item.event_time,
                supplemental_sources=(item.source,),
            )
        result.append(event)
    return tuple(result)
