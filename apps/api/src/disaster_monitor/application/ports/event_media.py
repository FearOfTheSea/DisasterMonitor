"""Ports for bounded event-media discovery and request-safe storage."""

from datetime import datetime
from typing import Protocol

from disaster_monitor.application.media import (
    DisasterMediaCandidate,
    DisasterMediaGallery,
    MediaEventContext,
    RetrievedMedia,
    StoredMediaAsset,
)


class EventMediaProvider(Protocol):
    @property
    def provider_id(self) -> str: ...

    async def discover(
        self, context: MediaEventContext, *, now: datetime
    ) -> tuple[DisasterMediaCandidate, ...]: ...

    async def retrieve(self, candidate: DisasterMediaCandidate) -> RetrievedMedia: ...


class MediaAssetStore(Protocol):
    def put(self, media: RetrievedMedia) -> StoredMediaAsset: ...

    def get(self, media_id: str) -> StoredMediaAsset | None: ...


class EventMediaDiscovery(Protocol):
    async def discover(
        self, context: MediaEventContext
    ) -> DisasterMediaGallery | None: ...
