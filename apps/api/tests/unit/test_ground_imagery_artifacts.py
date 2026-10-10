import hashlib
import json
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
    artifacts = {}
    for artifact_id in ("artifact:old", "artifact:referenced"):
        artifacts[artifact_id] = await store.put_bytes(
            artifact_id=artifact_id,
            content_type="image/tiff",
            content=artifact_id.encode(),
            maximum_bytes=100,
        )
    old_timestamp = (datetime.now(UTC) - timedelta(days=40)).timestamp()
    old_content = tmp_path / artifacts["artifact:old"].storage_key
    os.utime(old_content.with_suffix(".json"), (old_timestamp, old_timestamp))
    os.utime(old_content, (old_timestamp, old_timestamp))

    deleted = await store.delete_unreferenced(
        referenced_artifact_ids=frozenset({"artifact:referenced"}),
        older_than=datetime.now(UTC) - timedelta(days=30),
    )

    assert deleted == ("artifact:old",)
    assert await store.read("artifact:old") is None
    assert await store.read("artifact:referenced") is not None


@pytest.mark.asyncio
async def test_artifact_retry_at_full_budget_does_not_consume_storage(tmp_path) -> None:
    store = FilesystemImageryArtifactStore(tmp_path, maximum_total_bytes=5)
    arguments = dict(
        artifact_id="same", content_type="image/tiff", content=b"12345", maximum_bytes=5
    )
    first = await store.put_bytes(**arguments)
    assert await store.put_bytes(**arguments) == first
    assert len(list(tmp_path.glob("*.bin"))) == 1


@pytest.mark.asyncio
async def test_artifact_identity_uses_portable_case_sensitive_storage_keys(
    tmp_path,
) -> None:
    store = FilesystemImageryArtifactStore(tmp_path)
    keys = []
    for artifact_id in ("artifact:s2:latest", "CON", "con", "record."):
        stored = await store.put_bytes(
            artifact_id=artifact_id,
            content_type="image/tiff",
            content=artifact_id.encode(),
            maximum_bytes=100,
        )
        keys.append(stored.storage_key)
        assert ":" not in stored.storage_key
        reopened = await FilesystemImageryArtifactStore(tmp_path).read(artifact_id)
        assert reopened == (stored, artifact_id.encode())
    assert len(set(key.lower() for key in keys)) == len(keys)


@pytest.mark.asyncio
async def test_artifact_read_rejects_mismatched_metadata_identity(tmp_path) -> None:
    store = FilesystemImageryArtifactStore(tmp_path)
    stored = await store.put_bytes(
        artifact_id="expected",
        content_type="image/tiff",
        content=b"bytes",
        maximum_bytes=100,
    )
    metadata = (tmp_path / stored.storage_key).with_suffix(".json")
    document = json.loads(metadata.read_text(encoding="utf-8"))
    document["artifact_id"] = "different"
    metadata.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(ArtifactStorageError, match="identity"):
        await store.read("expected")


@pytest.mark.asyncio
async def test_artifact_store_preserves_preexisting_legacy_artifacts(tmp_path) -> None:
    content = b"legacy artifact"
    checksum = hashlib.sha256(content).hexdigest()
    (tmp_path / "legacy.bin").write_bytes(content)
    (tmp_path / "legacy.json").write_text(
        json.dumps(
            dict(
                artifact_id="legacy",
                content_type="image/tiff",
                storage_key="legacy.bin",
                byte_count=len(content),
                sha256=checksum,
                etag=f'"{checksum}"',
            )
        ),
        encoding="utf-8",
    )
    store = FilesystemImageryArtifactStore(tmp_path)
    stored = await store.read("legacy")
    assert stored is not None
    assert stored[1] == content
    assert (
        await store.put_bytes(
            artifact_id="legacy",
            content_type="image/tiff",
            content=content,
            maximum_bytes=100,
        )
        == stored[0]
    )
    await store.delete("legacy")
    assert await store.read("legacy") is None
    assert not list(tmp_path.glob("*.bin"))
    assert not list(tmp_path.glob("*.json"))


@pytest.mark.asyncio
async def test_cleanup_rejects_metadata_pointing_at_another_artifact(tmp_path) -> None:
    store = FilesystemImageryArtifactStore(tmp_path)
    first = await store.put_bytes(
        artifact_id="old", content_type="image/tiff", content=b"old", maximum_bytes=100
    )
    fresh = await store.put_bytes(
        artifact_id="fresh",
        content_type="image/tiff",
        content=b"fresh",
        maximum_bytes=100,
    )
    metadata = (tmp_path / first.storage_key).with_suffix(".json")
    document = json.loads(metadata.read_text(encoding="utf-8"))
    document["artifact_id"] = fresh.artifact_id
    metadata.write_text(json.dumps(document), encoding="utf-8")
    old_timestamp = (datetime.now(UTC) - timedelta(days=40)).timestamp()
    os.utime(metadata, (old_timestamp, old_timestamp))

    with pytest.raises(ArtifactStorageError, match="identity"):
        await store.delete_unreferenced(
            referenced_artifact_ids=frozenset(),
            older_than=datetime.now(UTC) - timedelta(days=30),
        )
    assert await store.read("fresh") == (fresh, b"fresh")
