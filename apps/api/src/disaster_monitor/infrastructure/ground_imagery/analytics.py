"""Infrastructure-owned, quality-gated Sentinel change measurements."""

from __future__ import annotations

import hashlib

import numpy as np

from disaster_monitor.domain.imagery.analysis import AnalyticalImageryFinding


class FloodChangeAlgorithm:
    """Measure strong radar backscatter decrease without classifying flood truth."""

    algorithm_id = "sentinel-1-flood-change"
    version = "1.0.0"
    ratio_threshold = 0.35
    noise_floor = 0.01
    minimum_valid_fraction = 0.1

    def measure(
        self,
        before_vv: np.ndarray,
        after_vv: np.ndarray,
        *,
        valid_mask: np.ndarray,
        source_product_ids: tuple[str, ...],
    ) -> AnalyticalImageryFinding:
        before, after, valid = _validated_arrays(before_vv, after_vv, valid_mask)
        valid &= before > self.noise_floor
        valid &= after >= 0
        _require_coverage(valid, self.minimum_valid_fraction)
        changed = valid & (
            after / np.maximum(before, self.noise_floor) <= self.ratio_threshold
        )
        metrics = _metrics(changed, valid)
        return _finding(
            self.algorithm_id,
            self.version,
            source_product_ids,
            metrics,
            (
                ("ratio_threshold", self.ratio_threshold),
                ("noise_floor", self.noise_floor),
            ),
            "Analytical Sentinel-1 backscatter decrease; this is not a verified "
            "flood extent.",
        )


class BurnChangeAlgorithm:
    """Measure NBR decrease where Sentinel-2 cloud and coverage gates pass."""

    algorithm_id = "sentinel-2-burn-change"
    version = "1.0.0"
    delta_nbr_threshold = 0.25
    maximum_cloud_fraction = 0.4
    minimum_valid_fraction = 0.1

    def measure(
        self,
        before_nir: np.ndarray,
        before_swir: np.ndarray,
        after_nir: np.ndarray,
        after_swir: np.ndarray,
        *,
        valid_mask: np.ndarray,
        cloud_fraction: float,
        source_product_ids: tuple[str, ...],
    ) -> AnalyticalImageryFinding:
        if not 0 <= cloud_fraction <= 1:
            raise ValueError("Cloud fraction must be between zero and one.")
        if cloud_fraction > self.maximum_cloud_fraction:
            raise ValueError("The Sentinel-2 cloud gate did not pass.")
        arrays = tuple(
            np.asarray(value, dtype=np.float64)
            for value in (before_nir, before_swir, after_nir, after_swir)
        )
        if not arrays or any(value.shape != arrays[0].shape for value in arrays):
            raise ValueError("Comparison arrays must use one aligned grid.")
        valid = np.asarray(valid_mask, dtype=bool)
        if valid.shape != arrays[0].shape:
            raise ValueError("The validity mask must match the comparison grid.")
        valid &= np.logical_and.reduce(tuple(np.isfinite(value) for value in arrays))
        _require_coverage(valid, self.minimum_valid_fraction)
        before_nbr = _normalized_difference(arrays[0], arrays[1])
        after_nbr = _normalized_difference(arrays[2], arrays[3])
        changed = valid & ((before_nbr - after_nbr) >= self.delta_nbr_threshold)
        metrics = _metrics(changed, valid)
        metrics["mean_delta_nbr"] = float(np.mean((before_nbr - after_nbr)[valid]))
        return _finding(
            self.algorithm_id,
            self.version,
            source_product_ids,
            metrics,
            (
                ("delta_nbr_threshold", self.delta_nbr_threshold),
                ("maximum_cloud_fraction", self.maximum_cloud_fraction),
            ),
            "Analytical Sentinel-2 NBR change; this is not official damage grading.",
        )


def _validated_arrays(
    before: np.ndarray, after: np.ndarray, valid_mask: np.ndarray
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    first = np.asarray(before, dtype=np.float64)
    second = np.asarray(after, dtype=np.float64)
    valid = np.asarray(valid_mask, dtype=bool)
    if first.shape != second.shape or first.shape != valid.shape or first.size == 0:
        raise ValueError("Comparison arrays and masks must use one non-empty grid.")
    valid &= np.isfinite(first) & np.isfinite(second)
    return first, second, valid


def _require_coverage(valid: np.ndarray, minimum: float) -> None:
    if np.count_nonzero(valid) / valid.size < minimum:
        raise ValueError("The usable comparison coverage gate did not pass.")


def _normalized_difference(first: np.ndarray, second: np.ndarray) -> np.ndarray:
    denominator = first + second
    result: np.ndarray = np.divide(
        first - second,
        denominator,
        out=np.zeros_like(first),
        where=np.abs(denominator) > 1e-9,
    )
    return result


def _metrics(changed: np.ndarray, valid: np.ndarray) -> dict[str, float]:
    usable = int(np.count_nonzero(valid))
    changed_count = int(np.count_nonzero(changed))
    return {
        "valid_pixel_count": float(usable),
        "changed_pixel_count": float(changed_count),
        "changed_fraction": changed_count / usable,
    }


def _finding(
    algorithm_id: str,
    version: str,
    source_product_ids: tuple[str, ...],
    metrics: dict[str, float],
    thresholds: tuple[tuple[str, float], ...],
    interpretation: str,
) -> AnalyticalImageryFinding:
    material = "|".join(
        (algorithm_id, version, *source_product_ids, repr(sorted(metrics.items())))
    )
    return AnalyticalImageryFinding(
        finding_id="imagery-finding:"
        + hashlib.sha256(material.encode()).hexdigest()[:24],
        algorithm_id=algorithm_id,
        algorithm_version=version,
        source_product_ids=source_product_ids,
        metrics=metrics,
        threshold_parameters=thresholds,
        interpretation=interpretation,
    )


__all__ = ["BurnChangeAlgorithm", "FloodChangeAlgorithm"]
