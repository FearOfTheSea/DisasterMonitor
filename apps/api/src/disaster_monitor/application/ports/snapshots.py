"""Ports for durable evidence snapshots, jobs, history, and attribution."""

from datetime import datetime
from typing import Protocol

from disaster_monitor.domain.operations import (
    SourceSnapshotRecord,
)


class ImmutableBlobStore(Protocol):
    """Content-addressed payload storage with explicit retention deletion."""

    def put(self, payload_sha256: str, content: bytes) -> str: ...

    def delete(self, blob_uri: str) -> None: ...


class SnapshotReader(Protocol):
    async def snapshots(
        self, *, source_id: str | None = None, limit: int = 100
    ) -> tuple[SourceSnapshotRecord, ...]: ...


class SnapshotWriter(Protocol):
    async def append_snapshot(self, snapshot: SourceSnapshotRecord) -> bool: ...

    async def snapshot_by_idempotency_key(
        self, idempotency_key: str
    ) -> SourceSnapshotRecord | None: ...


class SnapshotRetentionStore(SnapshotReader, Protocol):
    async def tombstone_snapshot(
        self,
        snapshot_id: str,
        *,
        deleted_at: datetime,
        reason: str,
    ) -> bool: ...
