"""Bounded direct public-COG retrieval and local grid processing."""

from __future__ import annotations

from urllib.parse import urlsplit

import httpx
import rasterio
from rasterio.io import MemoryFile
from rasterio.transform import from_bounds
from rasterio.vrt import WarpedVRT

from disaster_monitor.application.ports.ground_imagery.rendering import (
    GroundImageryRenderer,
    GroundImageryRenderError,
    RenderedRaster,
    RenderRequest,
)

_MAXIMUM_BYTES = 128 * 1024 * 1024
_FALLBACK_REASONS = frozenset(
    {
        "credentials_required",
        "credentials_unavailable",
        "permission_denied",
        "processing_timeout",
        "processing_network_error",
        "processing_unavailable",
        "quota_deferred",
    }
)


class PublicCogRenderer(GroundImageryRenderer):
    """Download one selected public COG and warp it on the local machine."""

    def __init__(
        self,
        *,
        allowed_hosts: frozenset[str],
        client: httpx.AsyncClient | None = None,
        timeout_seconds: float = 180,
        maximum_response_bytes: int = _MAXIMUM_BYTES,
    ) -> None:
        if not allowed_hosts:
            raise ValueError(
                "Direct COG processing requires an explicit host allowlist."
            )
        self._allowed_hosts = frozenset(host.casefold() for host in allowed_hosts)
        self._client = client or httpx.AsyncClient(timeout=timeout_seconds)
        self._owns_client = client is None
        self._maximum_response_bytes = maximum_response_bytes

    async def render(self, request: RenderRequest) -> RenderedRaster:
        asset_url = _cog_asset(request)
        _validate_url(asset_url, self._allowed_hosts)
        try:
            response = await self._client.get(
                asset_url,
                headers={
                    "Accept": "image/tiff, image/geotiff, application/octet-stream"
                },
                follow_redirects=False,
            )
            response.raise_for_status()
        except httpx.HTTPError as error:
            raise GroundImageryRenderError(
                "The selected public COG could not be downloaded.",
                reason_code="public_cog_download_failed",
                retryable=True,
            ) from error
        if len(response.content) > self._maximum_response_bytes:
            raise GroundImageryRenderError(
                "The selected public COG exceeds the local processing limit.",
                reason_code="public_cog_too_large",
                retryable=False,
            )
        try:
            content, descriptions = _warp_to_grid(response.content, request)
        except (rasterio.errors.RasterioError, ValueError) as error:
            raise GroundImageryRenderError(
                "The selected public COG could not be processed on the requested grid.",
                reason_code="public_cog_invalid",
                retryable=False,
            ) from error
        metadata = [
            ("processing_path", "direct_public_cog_local"),
            ("source_asset", asset_url),
            ("sensor", request.observation.sensor.value),
        ]
        if any(descriptions):
            metadata.append(
                ("band_order", ",".join(value or "unnamed" for value in descriptions))
            )
        return RenderedRaster(
            content=content,
            media_type="image/tiff",
            source_product_ids=(request.observation.identity.product_id,),
            provider_metadata=tuple(metadata),
        )

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()


class FallbackGroundImageryRenderer(GroundImageryRenderer):
    """Prefer remote rendering, then use local COGs for availability failures."""

    def __init__(
        self, primary: GroundImageryRenderer, local_fallback: GroundImageryRenderer
    ) -> None:
        self._primary = primary
        self._local_fallback = local_fallback

    async def render(self, request: RenderRequest) -> RenderedRaster:
        try:
            return await self._primary.render(request)
        except GroundImageryRenderError as error:
            if error.reason_code not in _FALLBACK_REASONS:
                raise
            return await self._local_fallback.render(request)

    async def aclose(self) -> None:
        await self._primary.aclose()
        await self._local_fallback.aclose()


def _cog_asset(request: RenderRequest) -> str:
    assets = dict(request.observation.assets)
    for key in ("cog", "data", "analytic", "visual"):
        value = assets.get(key)
        if value:
            return value
    raise GroundImageryRenderError(
        "The selected product does not expose a supported public COG asset.",
        reason_code="public_cog_unavailable",
        retryable=False,
    )


def _validate_url(url: str, allowed_hosts: frozenset[str]) -> None:
    try:
        parsed = urlsplit(url)
        port = parsed.port
    except ValueError as error:
        raise GroundImageryRenderError(
            "The public COG URL is invalid.",
            reason_code="public_cog_url_rejected",
            retryable=False,
        ) from error
    if (
        parsed.scheme != "https"
        or (parsed.hostname or "").casefold() not in allowed_hosts
        or parsed.username is not None
        or parsed.password is not None
        or port not in {None, 443}
        or parsed.fragment
    ):
        raise GroundImageryRenderError(
            "The public COG URL is outside the admitted boundary.",
            reason_code="public_cog_url_rejected",
            retryable=False,
        )


def _warp_to_grid(
    content: bytes, request: RenderRequest
) -> tuple[bytes, tuple[str | None, ...]]:
    grid = request.grid
    destination_transform = from_bounds(
        grid.min_x,
        grid.min_y,
        grid.max_x,
        grid.max_y,
        grid.width,
        grid.height,
    )
    with MemoryFile(content) as source_memory:
        with source_memory.open() as source:
            if source.crs is None or not 1 <= source.count <= 16:
                raise ValueError("Public COG requires a CRS and bounded band count.")
            descriptions = tuple(source.descriptions)
            with WarpedVRT(
                source,
                crs=grid.crs,
                transform=destination_transform,
                width=grid.width,
                height=grid.height,
            ) as warped:
                profile = warped.profile.copy()
                profile.update(
                    driver="GTiff",
                    tiled=True,
                    compress="DEFLATE",
                    blockxsize=256,
                    blockysize=256,
                )
                with MemoryFile() as destination_memory:
                    with destination_memory.open(**profile) as destination:
                        for index in range(1, warped.count + 1):
                            destination.write(warped.read(index), index)
                            if descriptions[index - 1]:
                                destination.set_band_description(
                                    index, descriptions[index - 1]
                                )
                    return destination_memory.read(), descriptions


__all__ = ["FallbackGroundImageryRenderer", "PublicCogRenderer"]
