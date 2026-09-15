"""Convert official GFM raster masks into bounded source observation regions."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime

import numpy as np
from affine import Affine
from rasterio.features import shapes
from rasterio.warp import transform_geom

from disaster_monitor.domain.imagery.regions import (
    AssociationStatus,
    RegionEvidence,
    RegionSource,
    RegionSourceKind,
    polygon_from_geojson,
)


@dataclass(frozen=True, slots=True)
class GfmMaskLineage:
    source_item_id: str
    source_asset_url: str
    source_sha256: str
    source_crs: str
    mask_band: str
    threshold_expression: str
    algorithm_version: str
    captured_at: datetime
    retrieved_at: datetime

    def __post_init__(self) -> None:
        if not all(
            value.strip()
            for value in (
                self.source_item_id,
                self.source_asset_url,
                self.source_sha256,
                self.source_crs,
                self.mask_band,
                self.threshold_expression,
                self.algorithm_version,
            )
        ):
            raise ValueError("GFM component extraction requires complete lineage.")
        if len(self.source_sha256) != 64:
            raise ValueError("GFM source checksums must be SHA-256 values.")
        for value in (self.captured_at, self.retrieved_at):
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError("GFM lineage times must be timezone-aware.")


@dataclass(frozen=True, slots=True)
class GfmExtractedComponent:
    evidence: RegionEvidence
    pixel_count: int


def extract_gfm_components(
    mask: np.ndarray,
    *,
    transform: Affine,
    lineage: GfmMaskLineage,
    minimum_pixels: int = 4,
    maximum_components: int = 100,
) -> tuple[GfmExtractedComponent, ...]:
    if mask.ndim != 2 or mask.size == 0:
        raise ValueError("A GFM mask must be a non-empty two-dimensional array.")
    if not 1 <= minimum_pixels <= mask.size:
        raise ValueError("The GFM minimum component size is invalid.")
    if not 1 <= maximum_components <= 500:
        raise ValueError("The GFM component limit must be between 1 and 500.")
    active = np.asarray(mask, dtype=bool)
    labels, counts = _label_components(active)
    records: list[GfmExtractedComponent] = []
    for geometry, label_value in shapes(labels, mask=labels > 0, transform=transform):
        label = int(label_value)
        count = counts[label]
        if count < minimum_pixels:
            continue
        wgs84 = (
            geometry
            if lineage.source_crs.upper() == "EPSG:4326"
            else transform_geom(lineage.source_crs, "EPSG:4326", geometry, precision=8)
        )
        component_id = f"{lineage.source_item_id}:component:{label}"
        evidence = RegionEvidence(
            evidence_id=f"gfm-mask:{component_id}",
            geometry=polygon_from_geojson(json.loads(json.dumps(wgs84))),
            source=RegionSource(
                source_id="cems-gfm-eodc",
                source_kind=RegionSourceKind.OBSERVATION_MASK,
                publisher="Copernicus Emergency Management Service / EODC",
                reference=lineage.source_asset_url,
                source_crs=lineage.source_crs,
                captured_at=lineage.captured_at,
                attribution="CEMS Global Flood Monitoring",
                metadata=(
                    ("source_item_id", lineage.source_item_id),
                    ("source_sha256", lineage.source_sha256),
                    ("mask_band", lineage.mask_band),
                    ("threshold", lineage.threshold_expression),
                    ("algorithm_version", lineage.algorithm_version),
                    ("pixel_count", str(count)),
                ),
            ),
            association=AssociationStatus.POSSIBLE,
            semantic_role="official observed flood extent",
            component_id=component_id,
            observed_at=lineage.captured_at,
            derivation_inputs=(
                lineage.source_item_id,
                lineage.source_sha256,
                lineage.threshold_expression,
                lineage.algorithm_version,
            ),
        )
        records.append(GfmExtractedComponent(evidence, count))
    return tuple(
        sorted(
            records,
            key=lambda item: (-item.pixel_count, item.evidence.component_id or ""),
        )[:maximum_components]
    )


def _label_components(mask: np.ndarray) -> tuple[np.ndarray, dict[int, int]]:
    labels = np.zeros(mask.shape, dtype=np.int32)
    counts: dict[int, int] = {}
    label = 0
    height, width = mask.shape
    for row in range(height):
        for column in range(width):
            if not mask[row, column] or labels[row, column]:
                continue
            label += 1
            stack = [(row, column)]
            labels[row, column] = label
            count = 0
            while stack:
                current_row, current_column = stack.pop()
                count += 1
                for next_row, next_column in (
                    (current_row - 1, current_column),
                    (current_row + 1, current_column),
                    (current_row, current_column - 1),
                    (current_row, current_column + 1),
                ):
                    if (
                        0 <= next_row < height
                        and 0 <= next_column < width
                        and mask[next_row, next_column]
                        and not labels[next_row, next_column]
                    ):
                        labels[next_row, next_column] = label
                        stack.append((next_row, next_column))
            counts[label] = count
    return labels, counts


__all__ = ["GfmExtractedComponent", "GfmMaskLineage", "extract_gfm_components"]
