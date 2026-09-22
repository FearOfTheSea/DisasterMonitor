"""Load reviewed terminology from source-controlled JSON files."""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path

from disaster_monitor.application.ports.terminology import TerminologyPackReader
from disaster_monitor.domain.terminology import TerminologyPack

_LANGUAGE = re.compile(r"^[a-z]{2,3}(?:-[A-Z]{2})?$")


class JsonTerminologyPackReader(TerminologyPackReader):
    def __init__(self, root: Path) -> None:
        self._root = root.resolve()

    def read(self, language: str) -> TerminologyPack:
        normalized = language.strip()
        if not _LANGUAGE.fullmatch(normalized):
            raise ValueError("Terminology language tag is invalid.")
        path = (self._root / f"{normalized}.json").resolve()
        if path.parent != self._root:
            raise ValueError("Terminology path escaped the configured root.")
        raw = json.loads(path.read_text(encoding="utf-8"))
        if raw.get("schema_version") != "terminology-pack.v1":
            raise ValueError("Unsupported terminology pack schema.")
        raw_terms = raw.get("terms")
        if not isinstance(raw_terms, dict):
            raise ValueError("Terminology pack terms must be an object.")
        return TerminologyPack(
            language=raw["language"],
            version=raw["version"],
            reviewed_by=raw["reviewed_by"],
            reviewed_at=datetime.fromisoformat(raw["reviewed_at"]),
            terms=tuple(
                sorted((str(key), str(value)) for key, value in raw_terms.items())
            ),
            human_reviewed=raw.get("human_reviewed", False),
        )


__all__ = ["JsonTerminologyPackReader"]
