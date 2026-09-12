"""Immutable local imagery artifacts with bounded staging and checksums."""

from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from uuid import uuid4

from disaster_monitor.application.ports.ground_imagery.artifacts import (
    ImageryArtifactStoreError,
    StoredArtifact,
)

_SAFE_ID = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._:-]{0,127}$")


class ArtifactStorageError(ImageryArtifactStoreError):
    """Artifact publication was refused before metadata could become visible."""


class FilesystemImageryArtifactStore:
    """Store immutable files below one configured directory.

    Raster validation and COG conversion happen before this store is called.
    The store only handles bounded bytes, safe names, checksums, and atomic
    publication.
    """

    def __init__(self, root: Path, *, maximum_total_bytes: int = 20 * 1024**3) -> None:
        if maximum_total_bytes < 1:
            raise ValueError("The imagery storage budget must be positive.")
        self._root = root
        self._maximum_total_bytes = maximum_total_bytes

    async def put_bytes(
        self,
        *,
        artifact_id: str,
        content_type: str,
        content: bytes,
        maximum_bytes: int,
    ) -> StoredArtifact:
        _validate_id(artifact_id)
        if len(content) > maximum_bytes:
            raise ArtifactStorageError("The imagery artifact exceeded its size limit.")
        if self._used_bytes() + len(content) > self._maximum_total_bytes:
            raise ArtifactStorageError("The imagery storage budget is full.")
        self._root.mkdir(parents=True, exist_ok=True)
        staging = self._root / ".staging"
        staging.mkdir(exist_ok=True)
        target = self._root / f"{artifact_id}.bin"
        metadata_target = self._root / f"{artifact_id}.json"
        if target.exists() or metadata_target.exists():
            existing = await self.read(artifact_id)
            if (
                existing is not None
                and existing[0].sha256 == hashlib.sha256(content).hexdigest()
            ):
                return existing[0]
            raise ArtifactStorageError("The artifact identity is already published.")
        temporary = staging / f"{artifact_id}.{uuid4().hex}.tmp"
        digest = hashlib.sha256()
        metadata_temporary = staging / f"{artifact_id}.{uuid4().hex}.json.tmp"
        published_content = False
        try:
            with temporary.open("wb") as handle:
                for offset in range(0, len(content), 1024 * 1024):
                    chunk = content[offset : offset + 1024 * 1024]
                    digest.update(chunk)
                    handle.write(chunk)
                handle.flush()
                os.fsync(handle.fileno())
            checksum = digest.hexdigest()
            stored = StoredArtifact(
                artifact_id=artifact_id,
                content_type=content_type,
                storage_key=f"{artifact_id}.bin",
                byte_count=len(content),
                sha256=checksum,
                etag=f'"{checksum}"',
            )
            with metadata_temporary.open("w", encoding="utf-8") as handle:
                json.dump(
                    {
                        "artifact_id": stored.artifact_id,
                        "content_type": stored.content_type,
                        "storage_key": stored.storage_key,
                        "byte_count": stored.byte_count,
                        "sha256": stored.sha256,
                        "etag": stored.etag,
                    },
                    handle,
                    sort_keys=True,
                )
                handle.flush()
                os.fsync(handle.fileno())
            try:
                os.link(temporary, target)
            except FileExistsError as error:
                existing = await self.read(artifact_id)
                if existing is not None and existing[0].sha256 == checksum:
                    return existing[0]
                raise ArtifactStorageError(
                    "The artifact identity is already published."
                ) from error
            published_content = True
            try:
                os.link(metadata_temporary, metadata_target)
            except FileExistsError as error:
                raise ArtifactStorageError(
                    "The artifact metadata identity is already published."
                ) from error
            return stored
        finally:
            if published_content and not metadata_target.exists():
                target.unlink(missing_ok=True)
            temporary.unlink(missing_ok=True)
            metadata_temporary.unlink(missing_ok=True)

    async def read(self, artifact_id: str) -> tuple[StoredArtifact, bytes] | None:
        _validate_id(artifact_id)
        metadata_path = self._root / f"{artifact_id}.json"
        content_path = self._root / f"{artifact_id}.bin"
        if not metadata_path.is_file() or not content_path.is_file():
            return None
        try:
            document = json.loads(metadata_path.read_text(encoding="utf-8"))
            stored = StoredArtifact(**document)
            content = content_path.read_bytes()
        except (OSError, ValueError, TypeError) as error:
            raise ArtifactStorageError(
                "The imagery artifact metadata is corrupt."
            ) from error
        if (
            len(content) != stored.byte_count
            or hashlib.sha256(content).hexdigest() != stored.sha256
        ):
            raise ArtifactStorageError("The imagery artifact checksum does not match.")
        return stored, content

    async def delete(self, artifact_id: str) -> None:
        _validate_id(artifact_id)
        for path in (
            self._root / f"{artifact_id}.bin",
            self._root / f"{artifact_id}.json",
        ):
            try:
                path.unlink()
            except FileNotFoundError:
                pass

    async def aclose(self) -> None:
        return None

    def _used_bytes(self) -> int:
        if not self._root.exists():
            return 0
        return sum(
            path.stat().st_size for path in self._root.glob("*.bin") if path.is_file()
        )


def _validate_id(value: str) -> None:
    if not _SAFE_ID.fullmatch(value):
        raise ArtifactStorageError("The imagery artifact ID is invalid.")
