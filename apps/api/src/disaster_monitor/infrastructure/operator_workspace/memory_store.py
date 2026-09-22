"""In-memory non-evidence operator workspace repository."""

from disaster_monitor.domain.operator_workspace import (
    AnalystNote,
    CaseNotebook,
    NotebookEntry,
    OperatorBookmark,
    RunbookTemplate,
)


class InMemoryOperatorWorkspaceStore:
    def __init__(self) -> None:
        self._notes: dict[str, AnalystNote] = {}
        self._bookmarks: dict[str, OperatorBookmark] = {}
        self._runbooks: dict[str, RunbookTemplate] = {}
        self._notebooks: dict[str, CaseNotebook] = {}
        self._notebook_entries: dict[str, NotebookEntry] = {}

    async def add_note(self, note: AnalystNote) -> None:
        self._notes.setdefault(note.note_id, note)

    async def add_bookmark(self, bookmark: OperatorBookmark) -> None:
        self._bookmarks.setdefault(bookmark.bookmark_id, bookmark)

    async def add_runbook(self, runbook: RunbookTemplate) -> None:
        self._runbooks.setdefault(runbook.template_id, runbook)

    async def add_notebook(self, notebook: CaseNotebook) -> None:
        self._notebooks.setdefault(notebook.notebook_id, notebook)

    async def add_notebook_entry(self, entry: NotebookEntry) -> None:
        if entry.notebook_id not in self._notebooks:
            raise LookupError(entry.notebook_id)
        self._notebook_entries.setdefault(entry.entry_id, entry)

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

    async def notebooks(self) -> tuple[CaseNotebook, ...]:
        return tuple(self._notebooks.values())

    async def notebook_entries(self, notebook_id: str) -> tuple[NotebookEntry, ...]:
        return tuple(
            item
            for item in self._notebook_entries.values()
            if item.notebook_id == notebook_id
        )
