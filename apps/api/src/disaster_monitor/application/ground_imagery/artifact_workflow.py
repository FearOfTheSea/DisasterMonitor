"""Prepare immutable imagery artifacts and serve bounded stored tiles."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime

from disaster_monitor.application.ground_imagery import identifiers as _identifiers
from disaster_monitor.application.ground_imagery.errors import (
    GroundImageryArtifactNotFound,
    GroundImageryError,
)
from disaster_monitor.application.ground_imagery.models import (
    GroundImageryRequest,
    ImageryArtifactReference,
)
from disaster_monitor.application.ground_imagery.resolve_region import (
    GroundImageryRegionResolver,
)
from disaster_monitor.application.ports.ground_imagery.artifacts import (
    ImageryArtifactStore,
    ImageryArtifactStoreError,
    StoredArtifact,
)
from disaster_monitor.application.ports.ground_imagery.rendering import (
    GroundImageryRasterValidator,
    GroundImageryRenderer,
    GroundImageryRenderError,
    GroundImageryTileRenderer,
    RenderRequest,
)
from disaster_monitor.domain.imagery.observations import Sensor, TemporalRole


class GroundImageryArtifactWorkflow:
    """Own provider rendering, validation, immutable publication, and tiles."""

    def __init__(
        self,
        region_resolver: GroundImageryRegionResolver,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        renderer: GroundImageryRenderer | None = None,
        raster_validator: GroundImageryRasterValidator | None = None,
        artifact_store: ImageryArtifactStore | None = None,
        tile_renderer: GroundImageryTileRenderer | None = None,
    ) -> None:
        self._region_resolver = region_resolver
        self._clock = clock
        self._renderer = renderer
        self._raster_validator = raster_validator
        self._artifact_store = artifact_store
        self._tile_renderer = tile_renderer

    async def prepare(
        self,
        request: GroundImageryRequest,
        *,
        sensor: Sensor,
        role: str,
        overview: bool,
        output_kind: str | None,
    ) -> GroundImageryRequest:
        if self._renderer is None:
            raise GroundImageryError(
                "Authenticated imagery processing is not configured."
            )
        if self._raster_validator is None or self._artifact_store is None:
            raise GroundImageryError(
                "The imagery artifact pipeline is not available on this deployment."
            )
        region = request.region_resolution.region
        if region is None:
            raise ValueError("An imagery region must be resolved before rendering.")
        if request.selection is None:
            raise ValueError("This imagery request has no catalog selection.")
        temporal_role = TemporalRole(role)
        outcome = request.selection.for_sensor(sensor).for_role(temporal_role)
        observation = outcome.observation
        if observation is None:
            raise ValueError("The requested imagery role has no selected observation.")
        grid = self._region_resolver.plan_grid(
            region.inspection, sensor, overview=overview
        )
        recipe_version = observation.recipe_version or _identifiers.default_recipe(
            sensor
        )
        requested_output_kind = output_kind or _identifiers.default_output_kind(sensor)
        try:
            rendered = await self._renderer.render(
                RenderRequest(
                    observation=observation,
                    region=region.inspection,
                    grid=grid,
                    recipe_version=recipe_version,
                    output_kind=requested_output_kind,
                )
            )
        except GroundImageryRenderError as error:
            raise GroundImageryError(f"{error.reason_code}: {error}") from error
        normalized = self._raster_validator.normalize(
            rendered,
            grid=grid,
            source_product_id=observation.identity.product_id,
        )
        current_selection_id = _identifiers.selection_id(
            request.request_id, sensor, temporal_role, observation
        )
        artifact_id = _identifiers.artifact_id(
            request,
            current_selection_id,
            sensor,
            temporal_role,
            recipe_version,
            requested_output_kind,
            grid,
        )
        try:
            stored = await self._artifact_store.put_bytes(
                artifact_id=artifact_id,
                content_type=normalized.media_type,
                content=normalized.content,
                maximum_bytes=128 * 1024 * 1024,
            )
        except ImageryArtifactStoreError as error:
            raise GroundImageryError(str(error)) from error
        artifact = ImageryArtifactReference(
            artifact_id=stored.artifact_id,
            selection_id=current_selection_id,
            sensor=sensor,
            role=temporal_role,
            output_kind=requested_output_kind,
            content_type=stored.content_type,
            storage_key=stored.storage_key,
            byte_count=stored.byte_count,
            sha256=stored.sha256,
            source_product_ids=normalized.source_product_ids,
            grid=grid,
            created_at=self._clock(),
        )
        return replace(
            request,
            artifacts=tuple(
                item for item in request.artifacts if item.artifact_id != artifact_id
            )
            + (artifact,),
            updated_at=self._clock(),
        )

    async def read_artifact(
        self, artifact_id: str
    ) -> tuple[StoredArtifact, bytes] | None:
        _identifiers.validate_artifact_id(artifact_id)
        if self._artifact_store is None:
            raise GroundImageryError("The imagery artifact store is not configured.")
        try:
            return await self._artifact_store.read(artifact_id)
        except ImageryArtifactStoreError as error:
            raise GroundImageryError(str(error)) from error

    async def render_tile(self, artifact_id: str, zoom: int, x: int, y: int) -> bytes:
        _identifiers.validate_artifact_id(artifact_id)
        if self._tile_renderer is None:
            raise GroundImageryError("Stored imagery tile rendering is not configured.")
        if self._artifact_store is not None:
            try:
                stored = await self._artifact_store.read(artifact_id)
            except ImageryArtifactStoreError as error:
                raise GroundImageryError(str(error)) from error
            if stored is None:
                raise GroundImageryArtifactNotFound(
                    "The imagery artifact was not found."
                )
        if not 0 <= zoom <= 22:
            raise ValueError("The imagery tile zoom is outside its bounds.")
        max_index = (1 << zoom) - 1
        if not 0 <= x <= max_index or not 0 <= y <= max_index:
            raise ValueError("The imagery tile coordinate is outside its bounds.")
        try:
            return await self._tile_renderer.tile(artifact_id, zoom, x, y)
        except ImageryArtifactStoreError as error:
            raise GroundImageryError(str(error)) from error
        except ValueError as error:
            raise GroundImageryError(
                "The stored imagery artifact could not be rendered."
            ) from error

    def readiness(self) -> dict[str, object]:
        if self._renderer is None:
            return {
                "state": "credentials_required",
                "detail": (
                    "Configure CDSE_CLIENT_ID and CDSE_CLIENT_SECRET to render "
                    "products."
                ),
            }
        if self._artifact_store is None or self._raster_validator is None:
            return {
                "state": "artifact_pipeline_unavailable",
                "detail": "The server has no validated imagery artifact pipeline.",
            }
        return {
            "state": "ready",
            "detail": (
                "Public catalog discovery and authenticated rendering are configured."
            ),
        }

    async def aclose(self) -> None:
        for resource in (self._renderer, self._artifact_store, self._tile_renderer):
            close = getattr(resource, "aclose", None)
            if close is not None:
                await close()


__all__ = ["GroundImageryArtifactWorkflow"]
