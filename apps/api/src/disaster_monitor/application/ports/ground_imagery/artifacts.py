"""Artifact-store contract that supports streaming and immutable publication."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


class ImageryArtifactStoreError(RuntimeError):
    """An artifact store could not safely read or publish imagery."""


@dataclass(frozen=True, slots=True)
class StoredArtifact:
    artifact_id: str
    content_type: str
    storage_key: str
    byte_count: int
    sha256: str
    etag: str


class ImageryArtifactStore(Protocol):
    async def put_bytes(
        self,
        *,
        artifact_id: str,
        content_type: str,
        content: bytes,
        maximum_bytes: int,
    ) -> StoredArtifact: ...

    async def read(self, artifact_id: str) -> tuple[StoredArtifact, bytes] | None: ...

    async def delete(self, artifact_id: str) -> None: ...

    async def delete_unreferenced(
        self,
        *,
        referenced_artifact_ids: frozenset[str],
        older_than: datetime,
    ) -> tuple[str, ...]: ...

    async def aclose(self) -> None: ...
