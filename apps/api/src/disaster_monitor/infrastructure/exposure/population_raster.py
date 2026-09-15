"""Local GeoTIFF population exposure adapter for WorldPop and GHSL."""

import hashlib
import os
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import httpx
import numpy as np
import rasterio
from rasterio.mask import mask

from disaster_monitor.domain.exposure import (
    ExposureDataset,
    ExposureDatasetRole,
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


class WorldPopRasterExposure(PopulationRasterExposure):
    """Primary locally cached WorldPop population surface."""

    def __init__(
        self,
        raster_path: Path,
        *,
        version: str,
        vintage: int,
        resolution_m: float,
        source_url: str,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        super().__init__(
            raster_path,
            ExposureDataset(
                dataset_id=f"worldpop-{version}",
                publisher="WorldPop",
                version=version,
                vintage=vintage,
                resolution_m=resolution_m,
                license_name="WorldPop Open Data License (CC BY 4.0)",
                source_url=source_url,
                role=ExposureDatasetRole.PRIMARY,
                uncertainty=(
                    "Modelled gridded population; census vintage, spatial allocation, "
                    "and cell aggregation introduce uncertainty."
                ),
            ),
            clock=clock,
        )


class GhslRasterExposure(PopulationRasterExposure):
    """Secondary locally cached GHSL population surface for fallback/cross-check."""

    def __init__(
        self,
        raster_path: Path,
        *,
        version: str,
        vintage: int,
        resolution_m: float,
        source_url: str,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        super().__init__(
            raster_path,
            ExposureDataset(
                dataset_id=f"ghsl-{version}",
                publisher="European Commission Joint Research Centre",
                version=version,
                vintage=vintage,
                resolution_m=resolution_m,
                license_name="European Commission reuse notice / CC BY 4.0",
                source_url=source_url,
                role=ExposureDatasetRole.SECONDARY,
                uncertainty=(
                    "Modelled resident-population grid; reference epoch, source "
                    "census, "
                    "and built-settlement allocation introduce uncertainty."
                ),
            ),
            clock=clock,
        )


class PopulationDatasetCache:
    """Bounded immutable downloader for reusable population raster datasets."""

    def __init__(
        self,
        root: Path,
        *,
        allowed_hosts: frozenset[str],
        max_bytes: int = 5_000_000_000,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        if max_bytes <= 0:
            raise ValueError("Population cache byte limit must be positive.")
        root.mkdir(parents=True, exist_ok=True)
        self._root = root.resolve()
        self._allowed_hosts = allowed_hosts
        self._max_bytes = max_bytes
        self._client = client or httpx.AsyncClient(timeout=120)
        self._owns_client = client is None

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def download(
        self, *, dataset_id: str, url: str, expected_sha256: str
    ) -> Path:
        from urllib.parse import urlparse

        if not dataset_id or any(
            character
            not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_."
            for character in dataset_id
        ):
            raise ValueError("Population dataset cache identity is invalid.")
        parsed = urlparse(url)
        if parsed.scheme != "https" or parsed.hostname not in self._allowed_hosts:
            raise ValueError("Population download URL is outside approved hosts.")
        if len(expected_sha256) != 64:
            raise ValueError("Population downloads require a SHA-256 checksum.")
        target = self._root / f"{dataset_id}.tif"
        if target.is_file() and _sha256(target) == expected_sha256:
            return target
        temporary = self._root / f".{dataset_id}.partial"
        digest = hashlib.sha256()
        size = 0
        try:
            async with self._client.stream(
                "GET", url, follow_redirects=False
            ) as response:
                response.raise_for_status()
                with temporary.open("wb") as output:
                    async for chunk in response.aiter_bytes():
                        size += len(chunk)
                        if size > self._max_bytes:
                            raise ValueError(
                                "Population raster exceeds the cache limit."
                            )
                        digest.update(chunk)
                        output.write(chunk)
            if digest.hexdigest() != expected_sha256:
                raise ValueError(
                    "Population raster checksum differs from its manifest."
                )
            os.replace(temporary, target)
        finally:
            if temporary.exists():
                temporary.unlink()
        return target


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()
