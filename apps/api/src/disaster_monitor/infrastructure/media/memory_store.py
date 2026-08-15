"""Bounded process-local storage for safely fetched source previews."""

from collections import OrderedDict
from hashlib import sha256

from disaster_monitor.application.media import RetrievedMedia, StoredMediaAsset


class InMemoryMediaAssetStore:
    def __init__(self, *, maximum_assets: int = 24, maximum_bytes: int = 24_000_000):
        self._maximum_assets = maximum_assets
        self._maximum_bytes = maximum_bytes
        self._assets: OrderedDict[str, StoredMediaAsset] = OrderedDict()
        self._byte_length = 0

    def put(self, media: RetrievedMedia) -> StoredMediaAsset:
        checksum = sha256(media.content).hexdigest()
        media_id = f"media:{checksum[:32]}"
        existing = self._assets.get(media_id)
        if existing is not None:
            self._assets.move_to_end(media_id)
            return existing
        if len(media.content) > self._maximum_bytes:
            raise ValueError("One source image exceeds the bounded media store.")
        stored = StoredMediaAsset(
            media_id=media_id,
            content=media.content,
            media_type=media.media_type,
            content_sha256=checksum,
        )
        self._assets[media_id] = stored
        self._byte_length += len(stored.content)
        self._evict()
        return stored

    def get(self, media_id: str) -> StoredMediaAsset | None:
        item = self._assets.get(media_id)
        if item is not None:
            self._assets.move_to_end(media_id)
        return item

    def _evict(self) -> None:
        while self._assets and (
            len(self._assets) > self._maximum_assets
            or self._byte_length > self._maximum_bytes
        ):
            _, removed = self._assets.popitem(last=False)
            self._byte_length -= len(removed.content)
