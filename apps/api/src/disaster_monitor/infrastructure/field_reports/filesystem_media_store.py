"""Content-addressed field-media storage after privacy transformation."""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path

from disaster_monitor.domain.field_reports import FieldMediaLineage


class FilesystemFieldMediaStore:
    def __init__(
        self,
        root: Path,
        *,
        maximum_bytes: int = 100_000_000,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        if maximum_bytes <= 0:
            raise ValueError("Field-media store byte limit must be positive.")
        self._root = root.resolve()
        self._root.mkdir(parents=True, exist_ok=True)
        self._maximum_bytes = maximum_bytes
        self._clock = clock
        self.purge_expired()

    def put(self, lineage: FieldMediaLineage, content: bytes) -> None:
        if sha256(content).hexdigest() != lineage.stored_sha256:
            raise ValueError("Field-media content does not match its lineage checksum.")
        target = self._path(lineage.media_id)
        if target.exists():
            if target.read_bytes() != content:
                raise RuntimeError("Field-media identity was reused.")
        else:
            self.purge_expired()
            used = sum(path.stat().st_size for path in self._root.rglob("*.bin"))
            if used + len(content) > self._maximum_bytes:
                raise ValueError("Field-media storage has reached its byte limit.")
            target.parent.mkdir(parents=True, exist_ok=True)
            self._atomic_write(target, content)
            metadata = json.dumps(
                {
                    "schema_version": "field-media-lineage.v1",
                    "media_id": lineage.media_id,
                    "media_type": lineage.media_type,
                    "retention_expires_at": lineage.retention_expires_at.isoformat(),
                },
                separators=(",", ":"),
            ).encode()
            self._atomic_write(self._metadata_path(lineage.media_id), metadata)

    def get(self, media_id: str) -> tuple[str, bytes] | None:
        target = self._path(media_id)
        if not target.is_file():
            return None
        metadata = self._metadata(media_id)
        if (
            metadata is None
            or datetime.fromisoformat(metadata["retention_expires_at"]) <= self._clock()
        ):
            self.delete(media_id)
            return None
        content = target.read_bytes()
        expected = media_id.removeprefix("field-media:")
        if sha256(content).hexdigest() != expected:
            return None
        return metadata["media_type"], content

    def delete(self, media_id: str) -> None:
        target = self._path(media_id)
        if target.is_file():
            target.unlink()
        metadata = self._metadata_path(media_id)
        if metadata.is_file():
            metadata.unlink()

    def purge_expired(self) -> int:
        removed = 0
        for path in self._root.rglob("*.json"):
            try:
                metadata = json.loads(path.read_text(encoding="utf-8"))
                expires_at = datetime.fromisoformat(metadata["retention_expires_at"])
                media_id = metadata["media_id"]
            except (json.JSONDecodeError, KeyError, TypeError, ValueError):
                digest = path.stem
                if len(digest) == 64 and all(
                    character in "0123456789abcdef" for character in digest
                ):
                    self.delete(f"field-media:{digest}")
                    removed += 1
                continue
            if expires_at <= self._clock():
                self.delete(media_id)
                removed += 1
        for path in self._root.rglob("*.bin"):
            if not path.with_suffix(".json").is_file():
                path.unlink()
                removed += 1
        return removed

    def _path(self, media_id: str) -> Path:
        digest = media_id.removeprefix("field-media:")
        if len(digest) != 64 or any(
            character not in "0123456789abcdef" for character in digest
        ):
            raise ValueError("Field-media identity is invalid.")
        return self._root / digest[:2] / f"{digest}.bin"

    def _metadata_path(self, media_id: str) -> Path:
        return self._path(media_id).with_suffix(".json")

    def _metadata(self, media_id: str) -> dict[str, str] | None:
        path = self._metadata_path(media_id)
        if not path.is_file():
            return None
        try:
            metadata = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None
        if (
            metadata.get("schema_version") != "field-media-lineage.v1"
            or metadata.get("media_id") != media_id
            or metadata.get("media_type") not in {"image/jpeg", "image/png"}
            or not isinstance(metadata.get("retention_expires_at"), str)
        ):
            return None
        try:
            expires_at = datetime.fromisoformat(metadata["retention_expires_at"])
        except ValueError:
            return None
        if expires_at.tzinfo is None or expires_at.utcoffset() is None:
            return None
        return {
            "schema_version": metadata["schema_version"],
            "media_id": metadata["media_id"],
            "media_type": metadata["media_type"],
            "retention_expires_at": metadata["retention_expires_at"],
        }

    @staticmethod
    def _atomic_write(path: Path, content: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(f"{path.suffix}.tmp")
        with temporary.open("wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, 0o600)
        temporary.replace(path)
