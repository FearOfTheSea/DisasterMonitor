"""Immutable local imagery artifacts with bounded staging and checksums."""

from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from disaster_monitor.application.ports.ground_imagery.artifacts import (
    ImageryArtifactStoreError,
    StoredArtifact,
)

_SAFE_ID = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._:-]{0,127}$")
_WINDOWS_DEVICE_NAME = re.compile(r"^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\.|$)", re.I)


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
        self._root.mkdir(parents=True, exist_ok=True)
        staging = self._root / ".staging"
        staging.mkdir(exist_ok=True)
        target, metadata_target = self._artifact_paths(artifact_id)
        if target.exists() or metadata_target.exists():
            existing = await self.read(artifact_id)
            if (
                existing is not None
                and existing[0].sha256 == hashlib.sha256(content).hexdigest()
            ):
                return existing[0]
            raise ArtifactStorageError("The artifact identity is already published.")
        if self._used_bytes() + len(content) > self._maximum_total_bytes:
            raise ArtifactStorageError("The imagery storage budget is full.")
        temporary = staging / f"{target.stem}.{uuid4().hex}.tmp"
        digest = hashlib.sha256()
        metadata_temporary = staging / f"{target.stem}.{uuid4().hex}.json.tmp"
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
                storage_key=target.name,
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
        content_path, metadata_path = self._artifact_paths(artifact_id)
        if not metadata_path.is_file() or not content_path.is_file():
            return None
        try:
            document = json.loads(metadata_path.read_text(encoding="utf-8"))
            stored = StoredArtifact(**document)
            if (
                stored.artifact_id != artifact_id
                or stored.storage_key != content_path.name
            ):
                raise ArtifactStorageError(
                    "The imagery artifact identity does not match."
                )
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
        for path in self._artifact_paths(artifact_id):
            try:
                path.unlink()
            except FileNotFoundError:
                pass

    async def delete_unreferenced(
        self,
        *,
        referenced_artifact_ids: frozenset[str],
        older_than: datetime,
    ) -> tuple[str, ...]:
        """Delete only old artifacts that have no durable request reference."""
        if older_than.tzinfo is None or older_than.utcoffset() is None:
            raise ArtifactStorageError("Artifact cleanup requires an aware cutoff.")
        if not self._root.exists():
            return ()
        deleted: list[str] = []
        for metadata_path in sorted(self._root.glob("*.json")):
            try:
                document = json.loads(metadata_path.read_text(encoding="utf-8"))
                artifact_id = str(document["artifact_id"])
                _validate_id(artifact_id)
                content_path, expected_metadata_path = self._artifact_paths(artifact_id)
                if (
                    metadata_path != expected_metadata_path
                    or document["storage_key"] != content_path.name
                ):
                    raise ArtifactStorageError(
                        "The imagery artifact identity does not match."
                    )
                modified_at = datetime.fromtimestamp(
                    metadata_path.stat().st_mtime, tz=older_than.tzinfo
                )
            except (
                OSError,
                KeyError,
                TypeError,
                ValueError,
                json.JSONDecodeError,
            ) as error:
                raise ArtifactStorageError(
                    "The imagery artifact metadata is corrupt."
                ) from error
            if artifact_id in referenced_artifact_ids or modified_at >= older_than:
                continue
            await self.delete(artifact_id)
            deleted.append(artifact_id)
        return tuple(deleted)

    async def aclose(self) -> None:
        return None

    def _artifact_paths(self, artifact_id: str) -> tuple[Path, Path]:
        # Domain IDs can contain colons, reserved device names, or case-only variants.
        # Fixed-length hashes retain those identities on all supported filesystems.
        stem = "artifact-" + hashlib.sha256(artifact_id.encode("utf-8")).hexdigest()
        content = self._root / f"{stem}.bin"
        metadata = self._root / f"{stem}.json"
        legacy_name_supported = os.name != "nt" or (
            ":" not in artifact_id and not _WINDOWS_DEVICE_NAME.match(artifact_id)
        )
        if not content.exists() and not metadata.exists() and legacy_name_supported:
            legacy_content = self._root / f"{artifact_id}.bin"
            legacy_metadata = self._root / f"{artifact_id}.json"
            if legacy_content.exists() or legacy_metadata.exists():
                return legacy_content, legacy_metadata
        return content, metadata

    def _used_bytes(self) -> int:
        if not self._root.exists():
            return 0
        return sum(
            path.stat().st_size for path in self._root.glob("*.bin") if path.is_file()
        )


def _validate_id(value: str) -> None:
    if not _SAFE_ID.fullmatch(value):
        raise ArtifactStorageError("The imagery artifact ID is invalid.")
