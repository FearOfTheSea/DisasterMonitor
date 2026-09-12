"""Raster validation, COG normalization, and stored-artifact tile rendering."""

from __future__ import annotations

from typing import Any, cast

import numpy as np
import rasterio
from rasterio.enums import Resampling
from rasterio.io import MemoryFile
from rasterio.warp import transform_bounds
from rasterio.windows import Window
from rasterio.windows import from_bounds as window_from_bounds

from disaster_monitor.application.ports.ground_imagery.artifacts import (
    ImageryArtifactStore,
)
from disaster_monitor.application.ports.ground_imagery.rendering import (
    GroundImageryRasterValidator,
    ImageryGrid,
    RenderedRaster,
)

_MAX_BYTES = 128 * 1024 * 1024
_TILE_SIZE = 256
_WEB_MERCATOR_HALF_WORLD = 20_037_508.342789244


class RasterValidationError(ValueError):
    """A provider raster cannot be safely published as imagery."""


class RasterioCogValidator(GroundImageryRasterValidator):
    """Validate bounded GeoTIFFs and rewrite them to immutable tiled COGs."""

    def normalize(
        self,
        raster: RenderedRaster,
        *,
        grid: ImageryGrid,
        source_product_id: str,
    ) -> RenderedRaster:
        if raster.source_product_ids != (source_product_id,):
            raise RasterValidationError(
                "The raster source identity does not match the selected product."
            )
        if len(raster.content) > _MAX_BYTES:
            raise RasterValidationError("The raster response exceeds 128 MiB.")
        with MemoryFile(raster.content) as source_memory:
            try:
                with source_memory.open() as source:
                    self._validate_dataset(source, grid)
                    converted = _write_cog(source)
            except (rasterio.errors.RasterioIOError, ValueError) as error:
                if isinstance(error, RasterValidationError):
                    raise
                raise RasterValidationError(
                    "The provider response is not a readable georeferenced GeoTIFF."
                ) from error
        if not converted:
            raise RasterValidationError("The normalized raster is empty.")
        if len(converted) > _MAX_BYTES:
            raise RasterValidationError("The normalized raster exceeds 128 MiB.")
        return RenderedRaster(
            content=converted,
            media_type="image/tiff",
            source_product_ids=raster.source_product_ids,
            provider_metadata=(*raster.provider_metadata, ("format", "COG")),
        )

    @staticmethod
    def _validate_dataset(dataset: Any, grid: ImageryGrid) -> None:
        if dataset.driver not in {"GTiff", "COG"}:
            raise RasterValidationError("The raster driver is not GeoTIFF-compatible.")
        if not 1 <= dataset.count <= 16:
            raise RasterValidationError("The raster band count is outside its limit.")
        if dataset.width < 1 or dataset.height < 1:
            raise RasterValidationError("The raster has no pixels.")
        if dataset.width > grid.width or dataset.height > grid.height:
            raise RasterValidationError(
                "The raster dimensions exceed the requested grid."
            )
        if dataset.crs is None:
            raise RasterValidationError("The raster does not declare a CRS.")
        if not _valid_transform(dataset.transform):
            raise RasterValidationError("The raster transform is invalid.")
        if grid.crs and dataset.crs.to_string() != grid.crs:
            raise RasterValidationError(
                "The raster CRS does not match the selected metric grid."
            )
        expected_bounds = (grid.min_x, grid.min_y, grid.max_x, grid.max_y)
        actual_bounds = (
            dataset.bounds.left,
            dataset.bounds.bottom,
            dataset.bounds.right,
            dataset.bounds.top,
        )
        if any(
            abs(actual - expected) > 1e-3
            for actual, expected in zip(actual_bounds, expected_bounds, strict=True)
        ):
            raise RasterValidationError(
                "The raster bounds do not match the selected imagery grid."
            )
        if dataset.transform.b != 0 or dataset.transform.d != 0:
            raise RasterValidationError("Rotated imagery grids are not supported.")
        sample = dataset.read(
            1,
            out_shape=(1, min(dataset.height, 128), min(dataset.width, 128)),
            masked=True,
        )
        if np.ma.count(sample) == 0:
            raise RasterValidationError("The raster contains no usable sample data.")


def _write_cog(source: Any) -> bytes:
    profile = source.profile.copy()
    profile.update(
        driver="COG",
        compress="DEFLATE",
        BIGTIFF="IF_SAFER",
        blocksize=256,
        overview_resampling="nearest",
    )
    with MemoryFile() as destination_memory:
        with destination_memory.open(**profile) as destination:
            for _, window in source.block_windows(1):
                destination.write(source.read(window=window), window=window)
        return cast(bytes, destination_memory.read())


def _valid_transform(value: Any) -> bool:
    coefficients = (value.a, value.b, value.c, value.d, value.e, value.f)
    if not all(np.isfinite(coefficients)):
        return False
    return bool(
        abs(coefficients[0] * coefficients[4] - coefficients[1] * coefficients[3])
        > 1e-12
    )


class RasterioStoredArtifactTileRenderer:
    """Render transparent XYZ tiles from a stored COG, never from provider URLs."""

    def __init__(self, artifacts: ImageryArtifactStore) -> None:
        self._artifacts = artifacts

    async def tile(self, artifact_id: str, zoom: int, x: int, y: int) -> bytes:
        stored = await self._artifacts.read(artifact_id)
        if stored is None:
            raise RasterValidationError("The imagery artifact was not found.")
        _, content = stored
        with MemoryFile(content) as memory:
            try:
                with memory.open() as dataset:
                    return _tile_bytes(dataset, zoom, x, y)
            except rasterio.errors.RasterioIOError as error:
                raise RasterValidationError(
                    "The stored imagery artifact is not a readable COG."
                ) from error


def _tile_bytes(dataset: Any, zoom: int, x: int, y: int) -> bytes:
    left, bottom, right, top = _xyz_bounds(zoom, x, y)
    bounds = transform_bounds(
        "EPSG:3857", dataset.crs, left, bottom, right, top, densify_pts=21
    )
    requested = window_from_bounds(*bounds, transform=dataset.transform)
    full = Window(0, 0, dataset.width, dataset.height)
    intersection = requested.intersection(full)
    if intersection.width <= 0 or intersection.height <= 0:
        return _transparent_png()
    values = dataset.read(
        out_shape=(dataset.count, _TILE_SIZE, _TILE_SIZE),
        window=requested,
        boundless=True,
        masked=True,
        resampling=Resampling.nearest,
    )
    if values.shape[0] == 1:
        channels = np.repeat(values[:1], 3, axis=0)
    else:
        channels = values[:3]
    rgba = np.zeros((4, _TILE_SIZE, _TILE_SIZE), dtype=np.uint8)
    for index in range(3):
        rgba[index] = _to_byte(channels[index])
    mask = np.ma.getmaskarray(channels[0])
    if values.shape[0] >= 5:
        # Sentinel-2 display responses carry SCL before dataMask.  The
        # classification band is useful metadata, but it must never become
        # tile opacity.
        alpha = np.ma.getdata(values[4])
        rgba[3] = _to_byte(alpha)
        rgba[3][mask] = 0
    elif values.shape[0] == 4:
        alpha = np.ma.getdata(values[3])
        rgba[3] = _to_byte(alpha)
        rgba[3][mask] = 0
    else:
        rgba[3] = np.where(mask, 0, 255).astype(np.uint8)
    return _png_bytes(rgba)


def _xyz_bounds(zoom: int, x: int, y: int) -> tuple[float, float, float, float]:
    scale = (2**zoom) * _WEB_MERCATOR_HALF_WORLD
    left = -_WEB_MERCATOR_HALF_WORLD + x * (2 * _WEB_MERCATOR_HALF_WORLD / 2**zoom)
    right = -_WEB_MERCATOR_HALF_WORLD + (x + 1) * (
        2 * _WEB_MERCATOR_HALF_WORLD / 2**zoom
    )
    top = _WEB_MERCATOR_HALF_WORLD - y * (2 * _WEB_MERCATOR_HALF_WORLD / 2**zoom)
    bottom = _WEB_MERCATOR_HALF_WORLD - (y + 1) * (
        2 * _WEB_MERCATOR_HALF_WORLD / 2**zoom
    )
    del scale
    return left, bottom, right, top


def _to_byte(values: Any) -> np.ndarray:
    data = np.ma.array(values, dtype=np.float32).filled(np.nan)
    finite = data[np.isfinite(data)]
    if finite.size and float(np.nanmax(finite)) <= 1.5:
        data = data * 255
    data[~np.isfinite(data)] = 0
    return np.clip(data, 0, 255).astype(np.uint8)


def _png_bytes(rgba: np.ndarray) -> bytes:
    with MemoryFile() as memory:
        with memory.open(
            driver="PNG",
            width=_TILE_SIZE,
            height=_TILE_SIZE,
            count=4,
            dtype="uint8",
        ) as dataset:
            dataset.write(rgba)
        return cast(bytes, memory.read())


def _transparent_png() -> bytes:
    return _png_bytes(np.zeros((4, _TILE_SIZE, _TILE_SIZE), dtype=np.uint8))
