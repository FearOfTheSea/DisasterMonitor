import hashlib

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
