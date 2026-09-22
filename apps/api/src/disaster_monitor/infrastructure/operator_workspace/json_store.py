"""Durable local storage for explicitly non-evidence operator state."""

from __future__ import annotations

import asyncio
import json
import os
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from disaster_monitor.domain.operator_workspace import (
    AnalystNote,
    CaseNotebook,
    NotebookEntry,
    NotebookEntryKind,
    OperatorBookmark,
    RunbookTemplate,
)


class JsonOperatorWorkspaceStore:
    def __init__(self, path: Path) -> None:
        self._path = path.resolve()
        self._lock = asyncio.Lock()
        self._notes: dict[str, AnalystNote] = {}
        self._bookmarks: dict[str, OperatorBookmark] = {}
        self._runbooks: dict[str, RunbookTemplate] = {}
        self._notebooks: dict[str, CaseNotebook] = {}
        self._notebook_entries: dict[str, NotebookEntry] = {}
        self._load()

    async def add_note(self, note: AnalystNote) -> None:
        async with self._lock:
            self._notes.setdefault(note.note_id, note)
            self._persist()

    async def add_bookmark(self, bookmark: OperatorBookmark) -> None:
        async with self._lock:
            self._bookmarks.setdefault(bookmark.bookmark_id, bookmark)
            self._persist()

    async def add_runbook(self, runbook: RunbookTemplate) -> None:
        async with self._lock:
            self._runbooks.setdefault(runbook.template_id, runbook)
            self._persist()

    async def add_notebook(self, notebook: CaseNotebook) -> None:
        async with self._lock:
            self._notebooks.setdefault(notebook.notebook_id, notebook)
            self._persist()

    async def add_notebook_entry(self, entry: NotebookEntry) -> None:
        async with self._lock:
            if entry.notebook_id not in self._notebooks:
                raise LookupError(entry.notebook_id)
            self._notebook_entries.setdefault(entry.entry_id, entry)
            self._persist()

    async def notes(self, incident_id: str | None) -> tuple[AnalystNote, ...]:
        return tuple(
            note for note in self._notes.values() if note.incident_id == incident_id
        )

    async def bookmarks(self, incident_id: str | None) -> tuple[OperatorBookmark, ...]:
        return tuple(
            bookmark
            for bookmark in self._bookmarks.values()
            if bookmark.incident_id == incident_id
        )

    async def runbooks(self) -> tuple[RunbookTemplate, ...]:
        return tuple(self._runbooks.values())

    async def notebooks(self) -> tuple[CaseNotebook, ...]:
        return tuple(self._notebooks.values())

    async def notebook_entries(self, notebook_id: str) -> tuple[NotebookEntry, ...]:
        return tuple(
            entry
            for entry in self._notebook_entries.values()
            if entry.notebook_id == notebook_id
        )

    def _load(self) -> None:
        if not self._path.is_file():
            return
        raw = json.loads(self._path.read_text(encoding="utf-8"))
        if raw.get("schema_version") not in {
            "operator-workspace-store.v1",
            "operator-workspace-store.v2",
        }:
            raise ValueError("Unsupported operator-workspace store schema.")
        self._notes = {
            item["note_id"]: AnalystNote(
                note_id=item["note_id"],
                incident_id=item.get("incident_id"),
                text=item["text"],
                tags=tuple(item.get("tags", [])),
                created_at=datetime.fromisoformat(item["created_at"]),
                evidence=item.get("evidence", False),
            )
            for item in raw.get("notes", [])
        }
        self._bookmarks = {
            item["bookmark_id"]: OperatorBookmark(
                bookmark_id=item["bookmark_id"],
                incident_id=item.get("incident_id"),
                target_type=item["target_type"],
                target_id=item["target_id"],
                label=item["label"],
                created_at=datetime.fromisoformat(item["created_at"]),
                evidence=item.get("evidence", False),
            )
            for item in raw.get("bookmarks", [])
        }
        self._runbooks = {
            item["template_id"]: RunbookTemplate(
                template_id=item["template_id"],
                name=item["name"],
                steps=tuple(item["steps"]),
                created_at=datetime.fromisoformat(item["created_at"]),
                autonomous_actions=item.get("autonomous_actions", False),
            )
            for item in raw.get("runbooks", [])
        }
        self._notebooks = {
            item["notebook_id"]: CaseNotebook(
                notebook_id=item["notebook_id"],
                title=item["title"],
                created_by=item["created_by"],
                created_at=datetime.fromisoformat(item["created_at"]),
                incident_ids=tuple(item.get("incident_ids", [])),
                evidence=item.get("evidence", False),
            )
            for item in raw.get("notebooks", [])
        }
        self._notebook_entries = {
            item["entry_id"]: NotebookEntry(
                entry_id=item["entry_id"],
                notebook_id=item["notebook_id"],
                kind=NotebookEntryKind(item["kind"]),
                title=item["title"],
                content=item["content"],
                reference_id=item.get("reference_id"),
                created_by=item["created_by"],
                created_at=datetime.fromisoformat(item["created_at"]),
                evidence=item.get("evidence", False),
                alters_canonical_state=item.get("alters_canonical_state", False),
            )
            for item in raw.get("notebook_entries", [])
        }

    def _persist(self) -> None:
        document = {
            "schema_version": "operator-workspace-store.v2",
            "notes": [_json_record(asdict(item)) for item in self._notes.values()],
            "bookmarks": [
                _json_record(asdict(item)) for item in self._bookmarks.values()
            ],
            "runbooks": [
                _json_record(asdict(item)) for item in self._runbooks.values()
            ],
            "notebooks": [
                _json_record(asdict(item)) for item in self._notebooks.values()
            ],
            "notebook_entries": [
                _json_record(asdict(item)) for item in self._notebook_entries.values()
            ],
        }
        self._path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self._path.with_suffix(f"{self._path.suffix}.tmp")
        with temporary.open("w", encoding="utf-8") as stream:
            json.dump(document, stream, ensure_ascii=False, separators=(",", ":"))
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, 0o600)
        temporary.replace(self._path)


def _json_record(record: dict[str, object]) -> dict[str, object]:
    return {
        key: (
            value.isoformat()
            if isinstance(value, datetime)
            else value.value
            if isinstance(value, NotebookEntryKind)
            else list(value)
            if isinstance(value, tuple)
            else value
        )
        for key, value in record.items()
    }
