"""At-least-once ingestion, immutable snapshots, and bounded worker policy."""

from __future__ import annotations

import hashlib

from disaster_monitor.application.ports.snapshots import (
    ImmutableBlobStore,
    SnapshotWriter,
)
from disaster_monitor.application.ports.source_payload import (
    AcquiredSourcePayload,
)
from disaster_monitor.domain.operations import (
    SourceSnapshotRecord,
)


def snapshot_idempotency_key(
    source_id: str,
    request_identity: str,
    provider_revision_or_payload_hash: str,
) -> str:
    """Use the roadmap's source + request + revision/payload identity."""
    material = "|".join(
        (source_id, request_identity, provider_revision_or_payload_hash)
    )
    return "sha256:" + hashlib.sha256(material.encode()).hexdigest()


class SnapshotPersistenceService:
    """Persist payload bytes before exposing normalized evidence downstream."""

    def __init__(
        self, repository: SnapshotWriter, blob_store: ImmutableBlobStore
    ) -> None:
        self._repository = repository
        self._blob_store = blob_store

    async def persist(self, payload: AcquiredSourcePayload) -> SourceSnapshotRecord:
        if not payload.content:
            raise ValueError("An empty provider response cannot become evidence.")
        checksum = "sha256:" + hashlib.sha256(payload.content).hexdigest()
        revision = payload.provider_revision or checksum
        idempotency = snapshot_idempotency_key(
            payload.source_id, payload.canonical_request_identity, revision
        )
        existing = await self._repository.snapshot_by_idempotency_key(idempotency)
        if existing is not None:
            return existing
        snapshot_id = f"source-snapshot:{idempotency.removeprefix('sha256:')[:24]}"
        blob_uri = self._blob_store.put(checksum, payload.content)
        snapshot = SourceSnapshotRecord(
            snapshot_id=snapshot_id,
            idempotency_key=idempotency,
            source_id=payload.source_id,
            canonical_request_identity=payload.canonical_request_identity,
            provider_revision=revision,
            retrieved_at=payload.retrieved_at,
            published_at=payload.published_at,
            observed_at=payload.observed_at,
            response_status=payload.response_status,
            content_type=payload.content_type,
            payload_sha256=checksum,
            payload_size_bytes=len(payload.content),
            blob_uri=blob_uri,
            rights_id=payload.rights_id,
        )
        created = await self._repository.append_snapshot(snapshot)
        if created:
            return snapshot
        existing = await self._repository.snapshot_by_idempotency_key(idempotency)
        if existing is None:
            raise RuntimeError("Snapshot idempotency conflict could not be resolved.")
        return existing
