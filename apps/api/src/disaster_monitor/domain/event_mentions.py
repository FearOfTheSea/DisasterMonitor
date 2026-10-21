"""Source-supported event mentions, independent of article and event identity."""

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from disaster_monitor.domain.disaster_types import Disaster
from disaster_monitor.domain.events import EventGeometry
from disaster_monitor.domain.evidence_types import SourceReference
from disaster_monitor.domain.mention_occurrence import MentionRole
from disaster_monitor.domain.reported_impacts import ReportedImpact


@dataclass(frozen=True, slots=True)
class MentionTime:
    wording: str
    start: datetime | None = None
    end: datetime | None = None
    precision: Literal["exact", "day", "range", "unknown"] = "unknown"
    year_inferred: bool = False

    def __post_init__(self) -> None:
        if any(t is not None and t.tzinfo is None for t in (self.start, self.end)):
            raise ValueError("Mention times require an explicit timezone.")
        if self.end is not None and (self.start is None or self.end < self.start):
            raise ValueError("Mention time bounds are invalid.")


@dataclass(frozen=True, slots=True)
class MentionPlace:
    wording: str
    precision: Literal["named_place", "country_context", "unresolved"]
    role: Literal["reported_location", "administrative_area"] = "reported_location"


@dataclass(frozen=True, slots=True)
class HazardEpisodeAccount:
    """One report's joint impacts, never allocated to its component hazards."""

    account_id: str
    hazards: tuple[Disaster, ...]
    place: MentionPlace
    time: MentionTime
    excerpt: str
    claims: tuple[ReportedImpact, ...]


@dataclass(frozen=True, slots=True)
class EventMention:
    mention_id: str
    source: SourceReference
    disaster: Disaster
    text: str
    excerpt: str
    place: MentionPlace | None = None
    time: MentionTime | None = None
    name: str | None = None
    role: MentionRole = "reported"
    geometry: EventGeometry | None = None
    claims: tuple[ReportedImpact, ...] = ()
    notices: tuple[str, ...] = ()
    distinguishing_evidence: str | None = None
    country_context: str | None = None
    occurrence_anchor_id: str | None = None
    episode_account: HazardEpisodeAccount | None = None

    def __post_init__(self) -> None:
        if not self.mention_id or not self.excerpt.strip():
            raise ValueError("Event mentions require identity and source evidence.")
