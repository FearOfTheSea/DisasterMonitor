"""Persistence seam for explicitly non-evidence operator workspace state."""

from typing import Protocol

from disaster_monitor.domain.operator_workspace import (
    AnalystNote,
    CaseNotebook,
    NotebookEntry,
    OperatorBookmark,
    RunbookTemplate,
)


class OperatorWorkspaceStore(Protocol):
    async def add_note(self, note: AnalystNote) -> None: ...

    async def add_bookmark(self, bookmark: OperatorBookmark) -> None: ...

    async def add_runbook(self, runbook: RunbookTemplate) -> None: ...

    async def add_notebook(self, notebook: CaseNotebook) -> None: ...

    async def add_notebook_entry(self, entry: NotebookEntry) -> None: ...

    async def notes(self, incident_id: str | None) -> tuple[AnalystNote, ...]: ...

    async def bookmarks(
        self, incident_id: str | None
    ) -> tuple[OperatorBookmark, ...]: ...

    async def runbooks(self) -> tuple[RunbookTemplate, ...]: ...

    async def notebooks(self) -> tuple[CaseNotebook, ...]: ...

    async def notebook_entries(self, notebook_id: str) -> tuple[NotebookEntry, ...]: ...
