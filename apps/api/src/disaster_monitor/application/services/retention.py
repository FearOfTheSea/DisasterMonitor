"""Rights-scoped content retention with permanent provenance tombstones."""

from dataclasses import dataclass
from datetime import datetime, timedelta

from disaster_monitor.application.ports.operational_state import (
    ImmutableBlobStore,
    OperationalRepository,
)


@dataclass(frozen=True, slots=True)
class SnapshotRetentionPolicy:
    """An owner-approved rule for one exact source and rights registration."""

    source_id: str
    rights_id: str
    retain_for: timedelta
    deletion_reason: str

    def __post_init__(self) -> None:
        if not self.source_id or not self.rights_id or not self.deletion_reason.strip():
            raise ValueError("Retention policies require source, rights, and reason.")
        if self.retain_for <= timedelta(0):
            raise ValueError("Retention duration must be positive.")


@dataclass(frozen=True, slots=True)
class RetentionResult:
    examined: int
    tombstoned_snapshot_ids: tuple[str, ...]


class SnapshotRetentionExecutor:
    """Delete eligible blobs while retaining checksum and lineage metadata."""

    def __init__(
        self, repository: OperationalRepository, blob_store: ImmutableBlobStore
    ) -> None:
        self._repository = repository
        self._blob_store = blob_store

    async def execute(
        self, policy: SnapshotRetentionPolicy, *, now: datetime
    ) -> RetentionResult:
        if now.tzinfo is None:
            raise ValueError("Retention execution time must be timezone-aware.")
        snapshots = await self._repository.snapshots(
            source_id=policy.source_id, limit=500
        )
        deleted: list[str] = []
        cutoff = now - policy.retain_for
        for snapshot in snapshots:
            if (
                not snapshot.content_available
                or snapshot.rights_id != policy.rights_id
                or snapshot.retrieved_at > cutoff
            ):
                continue
            self._blob_store.delete(snapshot.blob_uri)
            if await self._repository.tombstone_snapshot(
                snapshot.snapshot_id,
                deleted_at=now,
                reason=policy.deletion_reason,
            ):
                deleted.append(snapshot.snapshot_id)
        return RetentionResult(len(snapshots), tuple(deleted))
