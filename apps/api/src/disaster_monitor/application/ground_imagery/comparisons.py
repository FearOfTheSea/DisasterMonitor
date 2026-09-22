"""Reproducible synchronized before/after Ground comparison manifests."""

import math
from dataclasses import dataclass
from datetime import datetime

from disaster_monitor.application.ports.ground_imagery.rendering import ImageryGrid


@dataclass(frozen=True, slots=True)
class ComparisonSide:
    product_id: str
    captured_at: datetime
    artifact_checksum: str
    mask_checksum: str


@dataclass(frozen=True, slots=True)
class GroundComparisonManifest:
    manifest_version: str
    comparison_id: str
    before: ComparisonSide
    after: ComparisonSide
    grid: ImageryGrid
    recipe_version: str
    coverage_mask_version: str
    normalization: str
    derived_metrics: tuple[tuple[str, float], ...]
    created_at: datetime
    view_modes: tuple[str, str] = ("side_by_side", "swipe")


class GroundComparisonBuilder:
    def build(
        self,
        *,
        comparison_id: str,
        before_product_id: str,
        after_product_id: str,
        before_capture: datetime,
        after_capture: datetime,
        before_checksum: str,
        after_checksum: str,
        before_grid: ImageryGrid,
        after_grid: ImageryGrid,
        recipe_version: str,
        coverage_mask_version: str,
        before_mask_checksum: str,
        after_mask_checksum: str,
        normalization: str,
        derived_metrics: tuple[tuple[str, float], ...],
        created_at: datetime,
    ) -> GroundComparisonManifest:
        identity_fields = (
            comparison_id,
            before_product_id,
            after_product_id,
            recipe_version,
            coverage_mask_version,
            normalization,
        )
        if any(not value.strip() for value in identity_fields):
            raise ValueError("Ground comparison identities and recipes are required.")
        if before_grid != after_grid:
            raise ValueError("Ground comparison inputs must use the same grid.")
        if any(
            value.tzinfo is None or value.utcoffset() is None
            for value in (before_capture, after_capture, created_at)
        ):
            raise ValueError("Ground comparison timestamps must be timezone-aware.")
        if before_capture >= after_capture:
            raise ValueError(
                "Ground comparison before capture must precede after capture."
            )
        checksums = (
            before_checksum,
            after_checksum,
            before_mask_checksum,
            after_mask_checksum,
        )
        if any(not _is_sha256(value) for value in checksums):
            raise ValueError("Ground comparison artifacts require SHA-256 checksums.")
        metric_names = [key for key, _ in derived_metrics]
        if (
            any(not key.strip() for key in metric_names)
            or len(metric_names) != len(set(metric_names))
            or any(not math.isfinite(value) for _, value in derived_metrics)
        ):
            raise ValueError(
                "Ground comparison metrics require finite and unique stable names."
            )
        return GroundComparisonManifest(
            manifest_version="ground-comparison-manifest-v1",
            comparison_id=comparison_id,
            before=ComparisonSide(
                before_product_id,
                before_capture,
                before_checksum,
                before_mask_checksum,
            ),
            after=ComparisonSide(
                after_product_id,
                after_capture,
                after_checksum,
                after_mask_checksum,
            ),
            grid=before_grid,
            recipe_version=recipe_version,
            coverage_mask_version=coverage_mask_version,
            normalization=normalization,
            derived_metrics=tuple(sorted(derived_metrics)),
            created_at=created_at,
        )


def _is_sha256(value: str) -> bool:
    return len(value) == 64 and all(
        character in "0123456789abcdef" for character in value
    )


def comparison_document(value: GroundComparisonManifest) -> dict[str, object]:
    return {
        "manifest_version": value.manifest_version,
        "comparison_id": value.comparison_id,
        "before": _side_document(value.before),
        "after": _side_document(value.after),
        "grid": {
            "crs": value.grid.crs,
            "bounds": [
                value.grid.min_x,
                value.grid.min_y,
                value.grid.max_x,
                value.grid.max_y,
            ],
            "pixel_size_m": value.grid.pixel_size_m,
            "width": value.grid.width,
            "height": value.grid.height,
            "resolution_label": value.grid.resolution_label,
        },
        "recipe_version": value.recipe_version,
        "coverage_mask_version": value.coverage_mask_version,
        "normalization": value.normalization,
        "derived_metrics": dict(value.derived_metrics),
        "view_modes": list(value.view_modes),
        "created_at": value.created_at.isoformat(),
    }


def _side_document(value: ComparisonSide) -> dict[str, str]:
    return {
        "product_id": value.product_id,
        "captured_at": value.captured_at.isoformat(),
        "artifact_sha256": value.artifact_checksum,
        "mask_sha256": value.mask_checksum,
    }
