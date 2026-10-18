"""Bound provider rendering by immutable product, recipe, region, and output grid."""

import asyncio
import hashlib
import json
from dataclasses import asdict

from disaster_monitor.application.ground_imagery.request_limits import (
    GroundImageryRateLimitExceeded,
    GroundImageryRequestLimiter,
)
from disaster_monitor.application.ports.ground_imagery.artifacts import (
    ImageryArtifactStore,
    StoredArtifact,
)
from disaster_monitor.application.ports.ground_imagery.rendering import (
    GroundImageryRasterValidator,
    GroundImageryRenderer,
    RenderedRaster,
    RenderRequest,
)


def raster_identity(request: RenderRequest) -> str:
    observation = request.observation
    identity = {
        "schema": "validated-cog-v1",
        "source": asdict(observation.identity),
        "capture": [
            observation.capture.start.isoformat(),
            observation.capture.end.isoformat(),
        ],
        "sensor": observation.sensor.value,
        "mode": observation.mode,
        "polarizations": observation.polarizations,
        "region": request.region.as_geojson(),
        "grid": asdict(request.grid),
        "recipe": request.recipe_version,
        "output": request.output_kind,
    }
    digest = hashlib.sha256(
        json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return "artifact:" + digest[:48]


class SharedRasterPreparation:
    """Only validated immutable bytes are shared. User selections stay separate.

    One active render and at most eight pending distinct preparations protect the
    small local machine. Cache reads use the artifact store's checksum verification
    and its existing retention/byte budget, including after an API restart.
    """

    def __init__(
        self,
        renderer: GroundImageryRenderer,
        validator: GroundImageryRasterValidator,
        store: ImageryArtifactStore,
        limiter: GroundImageryRequestLimiter | None,
    ) -> None:
        self._renderer = renderer
        self._validator = validator
        self._store = store
        self._limiter = limiter
        self._tasks: dict[str, asyncio.Task[tuple[StoredArtifact, RenderedRaster]]] = {}
        self._slot = asyncio.Semaphore(1)

    async def prepare(
        self, request: RenderRequest
    ) -> tuple[StoredArtifact, RenderedRaster, bool]:
        key = raster_identity(request)
        existing = await self._store.read(key)
        if existing is not None:
            stored, content = existing
            return (
                stored,
                RenderedRaster(
                    content=content,
                    media_type=stored.content_type,
                    source_product_ids=(request.observation.identity.product_id,),
                ),
                True,
            )
        task = self._tasks.get(key)
        reused = task is not None
        if task is None:
            if len(self._tasks) >= 8:
                raise GroundImageryRateLimitExceeded(
                    "Image preparation queue is full. Retry shortly.", 10
                )
            task = asyncio.create_task(self._execute(key, request))
            self._tasks[key] = task
            task.add_done_callback(
                lambda done: None if done.cancelled() else done.exception()
            )
        stored, raster = await asyncio.shield(task)
        return stored, raster, reused

    async def _execute(
        self, key: str, request: RenderRequest
    ) -> tuple[StoredArtifact, RenderedRaster]:
        try:
            async with asyncio.timeout(120):
                async with self._slot:
                    if self._limiter is not None:
                        await self._limiter.claim_preparation()
                    rendered = await self._renderer.render(request)
                    normalized = self._validator.normalize(
                        rendered,
                        grid=request.grid,
                        source_product_id=request.observation.identity.product_id,
                    )
                    stored = await self._store.put_bytes(
                        artifact_id=key,
                        content_type=normalized.media_type,
                        content=normalized.content,
                        maximum_bytes=128 * 1024 * 1024,
                    )
                    return stored, normalized
        finally:
            self._tasks.pop(key, None)

    async def aclose(self) -> None:
        tasks = tuple(self._tasks.values())
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
