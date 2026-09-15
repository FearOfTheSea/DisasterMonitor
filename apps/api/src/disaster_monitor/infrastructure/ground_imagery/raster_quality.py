"""Sensor-aware raster semantic and comparison-grid quality checks."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np


@dataclass(frozen=True, slots=True)
class RasterQualityRequirements:
    expected_band_order: tuple[str, ...] = ()
    data_mask_band: int | None = None
    scl_band: int | None = None
    radar_bands: tuple[int, ...] = ()
    radar_noise_floor: float = 0.0
    maximum_sub_noise_fraction: float = 1.0

    def __post_init__(self) -> None:
        if self.radar_noise_floor < 0:
            raise ValueError("Radar noise floors cannot be negative.")
        if not 0 <= self.maximum_sub_noise_fraction <= 1:
            raise ValueError("Sub-noise limits must be fractions.")


@dataclass(frozen=True, slots=True)
class RasterQualityReport:
    usable_fraction: float
    sub_noise_fraction: float
    band_order: tuple[str, ...]
    nodata_values: tuple[float | None, ...]


def assess_raster_quality(
    dataset: Any, requirements: RasterQualityRequirements
) -> RasterQualityReport:
    descriptions = tuple(value or "" for value in dataset.descriptions)
    if requirements.expected_band_order:
        if dataset.count != len(requirements.expected_band_order):
            raise ValueError(
                "The raster band count does not match the processing recipe."
            )
        if any(descriptions) and descriptions != requirements.expected_band_order:
            raise ValueError(
                "The raster band order does not match the processing recipe."
            )
    _validate_band_indexes(dataset.count, requirements)
    data_mask = np.ones((dataset.height, dataset.width), dtype=bool)
    if requirements.data_mask_band is not None:
        raw_mask = dataset.read(requirements.data_mask_band)
        if not np.all(np.isin(raw_mask[np.isfinite(raw_mask)], (0, 1))):
            raise ValueError("The raster data mask contains values outside 0 and 1.")
        data_mask &= raw_mask == 1
    dataset_mask = dataset.dataset_mask() > 0
    usable = data_mask & dataset_mask
    usable_fraction = float(np.count_nonzero(usable) / usable.size)
    if usable_fraction == 0:
        raise ValueError("The raster contains no usable mask coverage.")
    if requirements.scl_band is not None:
        scl = dataset.read(requirements.scl_band)
        finite = scl[np.isfinite(scl)]
        if not np.all(np.equal(finite, np.floor(finite))) or not np.all(
            (0 <= finite) & (finite <= 11)
        ):
            raise ValueError("The Sentinel-2 SCL band contains invalid classes.")
    sub_noise_fraction = 0.0
    if requirements.radar_bands:
        samples = np.stack(
            [
                dataset.read(index).astype(np.float64)
                for index in requirements.radar_bands
            ]
        )
        valid = np.broadcast_to(usable, samples.shape) & np.isfinite(samples)
        count = int(np.count_nonzero(valid))
        if count == 0:
            raise ValueError("The radar raster contains no usable samples.")
        sub_noise = valid & (samples <= requirements.radar_noise_floor)
        sub_noise_fraction = float(np.count_nonzero(sub_noise) / count)
        if sub_noise_fraction > requirements.maximum_sub_noise_fraction:
            raise ValueError("The radar raster exceeds its zero/sub-noise limit.")
    return RasterQualityReport(
        usable_fraction=usable_fraction,
        sub_noise_fraction=sub_noise_fraction,
        band_order=(
            descriptions if any(descriptions) else requirements.expected_band_order
        ),
        nodata_values=tuple(dataset.nodatavals),
    )


def require_aligned_comparison_grid(first: Any, second: Any) -> None:
    """Fail closed unless two datasets share exact grid semantics."""
    if (
        first.crs != second.crs
        or first.transform != second.transform
        or first.width != second.width
        or first.height != second.height
    ):
        raise ValueError("Comparison rasters do not share one aligned grid.")


def _validate_band_indexes(count: int, requirements: RasterQualityRequirements) -> None:
    indexes = (
        *(requirements.radar_bands),
        *(
            value
            for value in (requirements.data_mask_band, requirements.scl_band)
            if value
        ),
    )
    if any(index < 1 or index > count for index in indexes):
        raise ValueError("A raster semantic band index is outside the dataset.")


__all__ = [
    "RasterQualityReport",
    "RasterQualityRequirements",
    "assess_raster_quality",
    "require_aligned_comparison_grid",
]
