import hashlib
import os
from datetime import UTC, datetime, timedelta

import pytest

from disaster_monitor.infrastructure.ground_imagery.artifact_store import (
    ArtifactStorageError,
    FilesystemImageryArtifactStore,
)


@pytest.mark.asyncio
async def test_artifact_store_publishes_checksum_atomically_and_is_idempotent(
    tmp_path,
) -> None:
    store = FilesystemImageryArtifactStore(tmp_path, maximum_total_bytes=100)
    content = b"validated-geotiff-fixture"

    first = await store.put_bytes(
        artifact_id="artifact:s2:latest",
        content_type="image/tiff",
        content=content,
        maximum_bytes=100,
    )
    second = await store.put_bytes(
        artifact_id="artifact:s2:latest",
        content_type="image/tiff",
        content=content,
        maximum_bytes=100,
    )
    stored = await store.read("artifact:s2:latest")

    assert first == second
    assert stored is not None
    assert stored[0].sha256 == hashlib.sha256(content).hexdigest()
    assert stored[1] == content


@pytest.mark.asyncio
async def test_artifact_store_rejects_traversal_corruption_and_budget_overflow(
    tmp_path,
) -> None:
    store = FilesystemImageryArtifactStore(tmp_path, maximum_total_bytes=5)
    with pytest.raises(ArtifactStorageError):
        await store.put_bytes(
            artifact_id="../escape",
            content_type="image/tiff",
            content=b"x",
            maximum_bytes=5,
        )
    with pytest.raises(ArtifactStorageError):
        await store.put_bytes(
            artifact_id="too-big",
            content_type="image/tiff",
            content=b"123456",
            maximum_bytes=6,
        )


@pytest.mark.asyncio
async def test_artifact_cleanup_keeps_referenced_files_and_removes_old_orphans(
    tmp_path,
) -> None:
    store = FilesystemImageryArtifactStore(tmp_path, maximum_total_bytes=100)
    for artifact_id in ("artifact:old", "artifact:referenced"):
        await store.put_bytes(
            artifact_id=artifact_id,
            content_type="image/tiff",
            content=artifact_id.encode(),
            maximum_bytes=100,
        )
    old_timestamp = (datetime.now(UTC) - timedelta(days=40)).timestamp()
    os.utime(tmp_path / "artifact:old.json", (old_timestamp, old_timestamp))
    os.utime(tmp_path / "artifact:old.bin", (old_timestamp, old_timestamp))

    deleted = await store.delete_unreferenced(
        referenced_artifact_ids=frozenset({"artifact:referenced"}),
        older_than=datetime.now(UTC) - timedelta(days=30),
    )

    assert deleted == ("artifact:old",)
    assert await store.read("artifact:old") is None
    assert await store.read("artifact:referenced") is not None
