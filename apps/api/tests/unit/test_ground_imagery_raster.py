from pathlib import Path

import numpy as np
import pytest
from rasterio.io import MemoryFile
from rasterio.transform import from_bounds

from disaster_monitor.application.ports.ground_imagery.rendering import (
    ImageryGrid,
    RenderedRaster,
)
from disaster_monitor.infrastructure.ground_imagery.artifact_store import (
    FilesystemImageryArtifactStore,
)
from disaster_monitor.infrastructure.ground_imagery.raster_artifacts import (
    RasterioCogValidator,
    RasterioStoredArtifactTileRenderer,
    RasterValidationError,
)

GRID = ImageryGrid(
    "EPSG:32632",
    0,
    0,
    100,
    100,
    10,
    10,
    10,
    "native-10m",
)


def _geotiff() -> bytes:
    with MemoryFile() as memory:
        with memory.open(
            driver="GTiff",
            width=GRID.width,
            height=GRID.height,
            count=3,
            dtype="uint8",
            crs=GRID.crs,
            transform=from_bounds(
                GRID.min_x,
                GRID.min_y,
                GRID.max_x,
                GRID.max_y,
                GRID.width,
                GRID.height,
            ),
        ) as dataset:
            dataset.write(np.full((3, GRID.height, GRID.width), 100, dtype="uint8"))
        return memory.read()


def _sentinel_2_display_geotiff() -> bytes:
    world = 20_037_508.342789244
    values = np.zeros((5, 256, 256), dtype="float32")
    values[:3] = 0.5
    values[4] = 1.0
    values[4, :128, :128] = 0.0
    with MemoryFile() as memory:
        with memory.open(
            driver="GTiff",
            width=256,
            height=256,
            count=5,
            dtype="float32",
            crs="EPSG:3857",
            transform=from_bounds(-world, -world, world, world, 256, 256),
        ) as dataset:
            dataset.write(values)
        return memory.read()


def test_cog_validator_requires_selected_source_identity() -> None:
    raster = RenderedRaster(_geotiff(), "image/tiff", ("product-1",))

    with pytest.raises(RasterValidationError, match="source identity"):
        RasterioCogValidator().normalize(
            raster, grid=GRID, source_product_id="product-2"
        )


def test_cog_validator_requires_selected_grid_bounds() -> None:
    raster = RenderedRaster(_geotiff(), "image/tiff", ("product-1",))
    mismatched_grid = ImageryGrid(
        "EPSG:32632", 0, 0, 110, 100, 10, 10, 10, "native-10m"
    )

    with pytest.raises(RasterValidationError, match="bounds"):
        RasterioCogValidator().normalize(
            raster, grid=mismatched_grid, source_product_id="product-1"
        )


@pytest.mark.asyncio
async def test_cog_artifact_can_be_read_and_tiled(tmp_path: Path) -> None:
    normalized = RasterioCogValidator().normalize(
        RenderedRaster(_geotiff(), "image/tiff", ("product-1",)),
        grid=GRID,
        source_product_id="product-1",
    )
    store = FilesystemImageryArtifactStore(tmp_path)
    await store.put_bytes(
        artifact_id="artifact:1",
        content_type=normalized.media_type,
        content=normalized.content,
        maximum_bytes=128 * 1024 * 1024,
    )

    tile = await RasterioStoredArtifactTileRenderer(store).tile("artifact:1", 0, 0, 0)

    assert tile.startswith(b"\x89PNG\r\n\x1a\n")


@pytest.mark.asyncio
async def test_sentinel_2_data_mask_controls_tile_alpha(tmp_path: Path) -> None:
    store = FilesystemImageryArtifactStore(tmp_path)
    await store.put_bytes(
        artifact_id="artifact:s2-mask",
        content_type="image/tiff",
        content=_sentinel_2_display_geotiff(),
        maximum_bytes=128 * 1024 * 1024,
    )

    tile = await RasterioStoredArtifactTileRenderer(store).tile(
        "artifact:s2-mask", 0, 0, 0
    )

    with MemoryFile(tile) as memory:
        with memory.open() as dataset:
            alpha = dataset.read(4)
    assert np.any(alpha == 0)
    assert np.any(alpha == 255)
