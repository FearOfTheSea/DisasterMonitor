"""In-memory non-evidence operator workspace repository."""

from disaster_monitor.domain.operator_workspace import (
    AnalystNote,
    OperatorBookmark,
    RunbookTemplate,
)


class InMemoryOperatorWorkspaceStore:
    def __init__(self) -> None:
        self._notes: dict[str, AnalystNote] = {}
        self._bookmarks: dict[str, OperatorBookmark] = {}
        self._runbooks: dict[str, RunbookTemplate] = {}

    async def add_note(self, note: AnalystNote) -> None:
        self._notes.setdefault(note.note_id, note)

    async def add_bookmark(self, bookmark: OperatorBookmark) -> None:
        self._bookmarks.setdefault(bookmark.bookmark_id, bookmark)

    async def add_runbook(self, runbook: RunbookTemplate) -> None:
        self._runbooks.setdefault(runbook.template_id, runbook)

    async def notes(self, incident_id: str | None) -> tuple[AnalystNote, ...]:
        return tuple(
            item for item in self._notes.values() if item.incident_id == incident_id
        )

    async def bookmarks(self, incident_id: str | None) -> tuple[OperatorBookmark, ...]:
        return tuple(
            item for item in self._bookmarks.values() if item.incident_id == incident_id
        )

    async def runbooks(self) -> tuple[RunbookTemplate, ...]:
        return tuple(self._runbooks.values())
