"""Manage analyst state without admitting it to canonical world state."""

from collections.abc import Callable
from datetime import UTC, datetime
from hashlib import sha256

from disaster_monitor.application.ports.operator_workspace import (
    OperatorWorkspaceStore,
)
from disaster_monitor.domain.operator_workspace import (
    AnalystNote,
    CaseNotebook,
    NotebookEntry,
    NotebookEntryKind,
    OperatorBookmark,
    RunbookTemplate,
)


class OperatorWorkspaceService:
    def __init__(
        self,
        store: OperatorWorkspaceStore,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._store = store
        self._clock = clock

    async def add_note(
        self, *, incident_id: str | None, text: str, tags: tuple[str, ...] = ()
    ) -> AnalystNote:
        created_at = self._clock()
        note = AnalystNote(
            note_id=_identity("note", incident_id or "global", text, created_at),
            incident_id=incident_id,
            text=text.strip(),
            tags=tuple(dict.fromkeys(tag.strip() for tag in tags)),
            created_at=created_at,
        )
        await self._store.add_note(note)
        return note

    async def add_bookmark(
        self,
        *,
        incident_id: str | None,
        target_type: str,
        target_id: str,
        label: str,
    ) -> OperatorBookmark:
        created_at = self._clock()
        bookmark = OperatorBookmark(
            bookmark_id=_identity("bookmark", target_id, label, created_at),
            incident_id=incident_id,
            target_type=target_type,
            target_id=target_id,
            label=label,
            created_at=created_at,
        )
        await self._store.add_bookmark(bookmark)
        return bookmark

    async def create_runbook_template(
        self, *, name: str, steps: tuple[str, ...]
    ) -> RunbookTemplate:
        created_at = self._clock()
        runbook = RunbookTemplate(
            template_id=_identity("runbook", name, "|".join(steps), created_at),
            name=name,
            steps=steps,
            created_at=created_at,
        )
        await self._store.add_runbook(runbook)
        return runbook

    async def create_notebook(
        self,
        *,
        title: str,
        created_by: str,
        incident_ids: tuple[str, ...] = (),
    ) -> CaseNotebook:
        created_at = self._clock()
        notebook = CaseNotebook(
            notebook_id=_identity("case-notebook", created_by, title, created_at),
            title=title.strip(),
            created_by=created_by.strip(),
            created_at=created_at,
            incident_ids=tuple(dict.fromkeys(incident_ids)),
        )
        await self._store.add_notebook(notebook)
        return notebook

    async def add_notebook_entry(
        self,
        *,
        notebook_id: str,
        kind: NotebookEntryKind,
        title: str,
        content: str,
        reference_id: str | None,
        created_by: str,
    ) -> NotebookEntry:
        if not any(
            item.notebook_id == notebook_id for item in await self._store.notebooks()
        ):
            raise LookupError(notebook_id)
        created_at = self._clock()
        entry = NotebookEntry(
            entry_id=_identity(
                "notebook-entry",
                notebook_id,
                f"{kind.value}|{title}|{content}|{reference_id or ''}",
                created_at,
            ),
            notebook_id=notebook_id,
            kind=kind,
            title=title.strip(),
            content=content.strip(),
            reference_id=reference_id,
            created_by=created_by.strip(),
            created_at=created_at,
        )
        await self._store.add_notebook_entry(entry)
        return entry

    async def notebooks(self) -> tuple[CaseNotebook, ...]:
        return await self._store.notebooks()

    async def notebook_entries(self, notebook_id: str) -> tuple[NotebookEntry, ...]:
        if not any(
            item.notebook_id == notebook_id for item in await self._store.notebooks()
        ):
            raise LookupError(notebook_id)
        return await self._store.notebook_entries(notebook_id)

    async def export_state(self, *, incident_id: str | None) -> dict[str, object]:
        return {
            "boundary": "non_evidence_operator_state",
            "incident_id": incident_id,
            "notes": await self._store.notes(incident_id),
            "bookmarks": await self._store.bookmarks(incident_id),
            "runbooks": await self._store.runbooks(),
            "notebooks": await self._store.notebooks(),
        }


def _identity(kind: str, scope: str, content: str, created_at: datetime) -> str:
    digest = sha256(f"{scope}|{content}|{created_at.isoformat()}".encode()).hexdigest()
    return f"{kind}:{digest[:24]}"
