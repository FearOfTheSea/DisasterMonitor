"""Deterministic watch-digest grouping and rendering."""

from dataclasses import dataclass
from datetime import datetime

from disaster_monitor.domain.spatial_watches import WatchFinding


@dataclass(frozen=True, slots=True)
class WatchDigestGroup:
    kind: str
    count: int
    entries: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class WatchDigest:
    digest_id: str
    starts_at: datetime
    ends_at: datetime
    groups: tuple[WatchDigestGroup, ...]
    rendered_text: str


class WatchDigestBuilder:
    def build(
        self,
        *,
        digest_id: str,
        starts_at: datetime,
        ends_at: datetime,
        findings: tuple[WatchFinding, ...] = (),
        new_events: tuple[str, ...] = (),
        evidence_changes: tuple[str, ...] = (),
        warning_changes: tuple[str, ...] = (),
        source_degradations: tuple[str, ...] = (),
    ) -> WatchDigest:
        grouped = (
            ("asset_intersections", tuple(item.summary for item in findings)),
            ("new_events", new_events),
            ("evidence_changes", evidence_changes),
            ("warning_changes", warning_changes),
            ("source_degradations", source_degradations),
        )
        groups = tuple(
            WatchDigestGroup(kind, len(entries), tuple(sorted(set(entries))))
            for kind, entries in grouped
            if entries
        )
        rendered = "\n".join(
            f"{group.kind.replace('_', ' ').title()} ({group.count})\n"
            + "\n".join(f"- {entry}" for entry in group.entries)
            for group in groups
        )
        return WatchDigest(digest_id, starts_at, ends_at, groups, rendered)
