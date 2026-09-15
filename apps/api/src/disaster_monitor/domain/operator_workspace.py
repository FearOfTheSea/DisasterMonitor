"""Operator-owned notes, bookmarks, and checklists that are never evidence."""

from dataclasses import dataclass
from datetime import datetime

from disaster_monitor.domain.disaster_types import _is_aware


@dataclass(frozen=True, slots=True)
class AnalystNote:
    note_id: str
    incident_id: str | None
    text: str
    tags: tuple[str, ...]
    created_at: datetime
    evidence: bool = False

    def __post_init__(self) -> None:
        if not self.note_id.strip() or not self.text.strip():
            raise ValueError("Analyst notes require identity and text.")
        if len(self.text) > 10_000 or any(not tag.strip() for tag in self.tags):
            raise ValueError("Analyst note content is outside its bounds.")
        if not _is_aware(self.created_at) or self.evidence:
            raise ValueError("Analyst notes must remain timestamped non-evidence.")


@dataclass(frozen=True, slots=True)
class OperatorBookmark:
    bookmark_id: str
    incident_id: str | None
    target_type: str
    target_id: str
    label: str
    created_at: datetime
    evidence: bool = False

    def __post_init__(self) -> None:
        if any(
            not value.strip()
            for value in (
                self.bookmark_id,
                self.target_type,
                self.target_id,
                self.label,
            )
        ):
            raise ValueError("Bookmarks require complete target metadata.")
        if not _is_aware(self.created_at) or self.evidence:
            raise ValueError("Bookmarks must remain timestamped non-evidence.")


@dataclass(frozen=True, slots=True)
class RunbookTemplate:
    template_id: str
    name: str
    steps: tuple[str, ...]
    created_at: datetime
    autonomous_actions: bool = False

    def __post_init__(self) -> None:
        if not self.template_id.strip() or not self.name.strip() or not self.steps:
            raise ValueError("Runbook templates require identity, name, and steps.")
        if len(self.steps) > 100 or any(not step.strip() for step in self.steps):
            raise ValueError("Runbook steps are outside their bounds.")
        if not _is_aware(self.created_at) or self.autonomous_actions:
            raise ValueError("Runbooks cannot contain autonomous actions.")
