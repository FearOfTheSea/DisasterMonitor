"""Local GeoTIFF population exposure adapter for WorldPop and GHSL."""

import hashlib
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import rasterio
from rasterio.mask import mask

from disaster_monitor.domain.exposure import (
    ExposureDataset,
    ExposureGeometry,
    PopulationExposureEstimate,
)


class PopulationRasterExposure:
    def __init__(
        self,
        raster_path: Path,
        dataset: ExposureDataset,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        if not raster_path.is_file():
            raise ValueError(f"Population raster does not exist: {raster_path}")
        with rasterio.open(raster_path) as source:
            if source.count != 1 or source.crs is None or source.crs.to_epsg() != 4326:
                raise ValueError(
                    "Population rasters require one georeferenced EPSG:4326 band."
                )
        self._path = raster_path
        self._dataset = dataset
        self._clock = clock
        self._checksum = _sha256(raster_path)

    async def estimate(self, geometry: ExposureGeometry) -> PopulationExposureEstimate:
        with rasterio.open(self._path) as source:
            if source.count != 1 or source.crs is None:
                raise ValueError("Population rasters require one georeferenced band.")
            if source.crs.to_epsg() != 4326:
                raise ValueError(
                    "Population rasters must use EPSG:4326 in this adapter."
                )
            clipped, _ = mask(
                source,
                [geometry.geometry.as_geojson()],
                crop=True,
                filled=False,
                indexes=1,
            )
        values = np.ma.array(clipped, copy=False)
        valid = values.compressed()
        if valid.size == 0:
            raise ValueError(
                "The requested area has no valid population cells; coverage is missing."
            )
        if np.any(~np.isfinite(valid)) or np.any(valid < 0):
            raise ValueError("Population raster contains invalid admitted values.")
        population = float(valid.sum(dtype=np.float64))
        geometry_hash = geometry.geometry.sha256()
        identity = hashlib.sha256(
            f"{self._dataset.dataset_id}|{self._dataset.version}|{self._checksum}|{geometry_hash}".encode()
        ).hexdigest()[:24]
        return PopulationExposureEstimate(
            estimate_id=f"population-exposure:{identity}",
            population=population,
            dataset=self._dataset,
            geometry_hash=geometry_hash,
            calculated_at=self._clock(),
            lineage=(
                self._dataset.dataset_id,
                self._dataset.version,
                f"sha256:{self._checksum}",
                geometry.source_id,
                geometry.source_version,
                geometry_hash,
            ),
        )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()
