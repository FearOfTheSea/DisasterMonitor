"""Operator-owned notes, bookmarks, and checklists that are never evidence."""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

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


class NotebookEntryKind(StrEnum):
    SOURCE_SNAPSHOT = "source_snapshot"
    QUESTION = "question"
    ANALYTICAL_RUN = "analytical_run"
    CONCLUSION = "conclusion"


@dataclass(frozen=True, slots=True)
class CaseNotebook:
    notebook_id: str
    title: str
    created_by: str
    created_at: datetime
    incident_ids: tuple[str, ...]
    evidence: bool = False

    def __post_init__(self) -> None:
        if any(
            not value.strip()
            for value in (self.notebook_id, self.title, self.created_by)
        ):
            raise ValueError("Case notebooks require identity and attribution.")
        if len(self.title) > 500 or any(
            not incident_id.strip() for incident_id in self.incident_ids
        ):
            raise ValueError("Case notebook content is outside its bounds.")
        if not _is_aware(self.created_at) or self.evidence:
            raise ValueError("Case notebooks must remain timestamped non-evidence.")


@dataclass(frozen=True, slots=True)
class NotebookEntry:
    entry_id: str
    notebook_id: str
    kind: NotebookEntryKind
    title: str
    content: str
    reference_id: str | None
    created_by: str
    created_at: datetime
    evidence: bool = False
    alters_canonical_state: bool = False

    def __post_init__(self) -> None:
        if any(
            not value.strip()
            for value in (
                self.entry_id,
                self.notebook_id,
                self.title,
                self.content,
                self.created_by,
            )
        ):
            raise ValueError("Notebook entries require bounded attributed content.")
        if len(self.title) > 500 or len(self.content) > 20_000:
            raise ValueError("Notebook entry content is outside its bounds.")
        if self.reference_id is not None and not self.reference_id.strip():
            raise ValueError("Notebook reference IDs must not be empty.")
        reference_required = self.kind in {
            NotebookEntryKind.SOURCE_SNAPSHOT,
            NotebookEntryKind.ANALYTICAL_RUN,
        }
        if reference_required and self.reference_id is None:
            raise ValueError("Pinned notebook entries require a reference ID.")
        if not _is_aware(self.created_at):
            raise ValueError("Notebook entry time must be timezone-aware.")
        if self.evidence or self.alters_canonical_state:
            raise ValueError("Notebook entries cannot alter canonical evidence.")
