"""Durable content-addressed storage for admitted event source media."""

import re
from hashlib import sha256
from pathlib import Path

from disaster_monitor.application.media import RetrievedMedia, StoredMediaAsset
from disaster_monitor.infrastructure.operations.filesystem_blob_store import (
    FilesystemBlobStore,
)

_MEDIA_FORMATS = {"image/jpeg": "jpeg", "image/png": "png"}
_MEDIA_ID = re.compile(r"media:([a-f0-9]{64}):(jpeg|png)")


class FilesystemMediaAssetStore:
    """Keep immutable source previews usable for persisted conversations."""

    def __init__(self, root: Path, *, maximum_bytes: int = 24_000_000) -> None:
        if maximum_bytes <= 0:
            raise ValueError("The media store byte limit must be positive.")
        self._root = root.resolve()
        self._maximum_bytes = maximum_bytes
        self._blobs = FilesystemBlobStore(self._root)

    def put(self, media: RetrievedMedia) -> StoredMediaAsset:
        media_format = _MEDIA_FORMATS.get(media.media_type)
        if media_format is None:
            raise ValueError("Only admitted JPEG and PNG media can be stored.")
        checksum = sha256(media.content).hexdigest()
        checksum_key = f"sha256:{checksum}"
        existing = self._blobs.get(checksum_key)
        if existing is None:
            used_bytes = sum(item.stat().st_size for item in self._root.rglob("*.bin"))
            if used_bytes + len(media.content) > self._maximum_bytes:
                raise ValueError("The durable media store has reached its byte limit.")
            self._blobs.put(checksum_key, media.content)
        elif existing != media.content:
            raise RuntimeError("Content-addressed media checksum collision.")
        return StoredMediaAsset(
            media_id=f"media:{checksum}:{media_format}",
            content=media.content,
            media_type=media.media_type,
            content_sha256=checksum,
        )

    def get(self, media_id: str) -> StoredMediaAsset | None:
        match = _MEDIA_ID.fullmatch(media_id)
        if match is None:
            return None
        checksum, media_format = match.groups()
        content = self._blobs.get(f"sha256:{checksum}")
        if content is None or sha256(content).hexdigest() != checksum:
            return None
        media_type = "image/jpeg" if media_format == "jpeg" else "image/png"
        return StoredMediaAsset(media_id, content, media_type, checksum)
