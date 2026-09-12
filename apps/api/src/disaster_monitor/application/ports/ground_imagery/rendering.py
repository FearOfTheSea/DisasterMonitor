"""Bounded renderer contract for exact selected acquisitions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from disaster_monitor.domain.imagery.observations import Observation
from disaster_monitor.domain.imagery.regions import MultiPolygon


class GroundImageryRenderError(RuntimeError):
    """A bounded provider render failed with an actionable status."""

    def __init__(self, message: str, *, reason_code: str, retryable: bool) -> None:
        super().__init__(message)
        self.reason_code = reason_code
        self.retryable = retryable


@dataclass(frozen=True, slots=True)
class ImageryGrid:
    """A metric output grid recorded in every rendered artifact."""

    crs: str
    min_x: float
    min_y: float
    max_x: float
    max_y: float
    pixel_size_m: float
    width: int
    height: int
    resolution_label: str

    def __post_init__(self) -> None:
        if not self.crs.strip() or self.pixel_size_m <= 0:
            raise ValueError("An imagery grid requires CRS and positive pixel size.")
        if (
            self.width < 1
            or self.height < 1
            or self.width > 2_048
            or self.height > 2_048
        ):
            raise ValueError(
                "An imagery chunk must be no larger than 2,048 pixels per side."
            )
        if self.max_x <= self.min_x or self.max_y <= self.min_y:
            raise ValueError("An imagery grid bounds interval is invalid.")


@dataclass(frozen=True, slots=True)
class RenderRequest:
    """Provider-independent render request bound to one source group."""

    observation: Observation
    region: MultiPolygon
    grid: ImageryGrid
    recipe_version: str
    output_kind: str

    def __post_init__(self) -> None:
        if not self.recipe_version.strip() or not self.output_kind.strip():
            raise ValueError("A render request requires recipe and output identity.")


@dataclass(frozen=True, slots=True)
class RenderedRaster:
    """A bounded provider response before local validation/publication."""

    content: bytes
    media_type: str
    source_product_ids: tuple[str, ...]
    provider_metadata: tuple[tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        if not self.content or len(self.content) > 128 * 1024 * 1024:
            raise ValueError("A rendered raster must be non-empty and bounded.")
        if self.media_type not in {
            "image/tiff",
            "image/geotiff",
            "application/octet-stream",
        }:
            raise ValueError("Rendered raster content type is not supported.")
        if not self.source_product_ids:
            raise ValueError(
                "Rendered raster provenance must identify source products."
            )


class GroundImageryRenderer(Protocol):
    async def render(self, request: RenderRequest) -> RenderedRaster: ...

    async def aclose(self) -> None: ...


class GroundImageryRasterValidator(Protocol):
    """Validate provider bytes and publish a georeferenced artifact payload."""

    def normalize(
        self, raster: RenderedRaster, *, grid: ImageryGrid, source_product_id: str
    ) -> RenderedRaster: ...


class GroundImageryTileRenderer(Protocol):
    """Render tiles only from an already stored artifact identity."""

    async def tile(self, artifact_id: str, zoom: int, x: int, y: int) -> bytes: ...
