"""Source-backed delivered-impact and shaking-region projections."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any

from disaster_monitor.domain.earthquake_context import ShakeMapLayer
from disaster_monitor.domain.imagery.regions import (
    AssociationStatus,
    RegionEvidence,
    RegionSource,
    RegionSourceKind,
    polygon_from_geojson,
)


class CemsProductKind(StrEnum):
    DELINEATION = "delineation"
    GRADING = "grading"
    REFERENCE = "reference"


@dataclass(frozen=True, slots=True)
class CemsDeliveredProduct:
    activation_code: str
    product_id: str
    version: str
    kind: CemsProductKind
    geometry: Mapping[str, Any]
    source_url: str
    published_at: datetime

    def __post_init__(self) -> None:
        if not all(
            value.strip()
            for value in (
                self.activation_code,
                self.product_id,
                self.version,
                self.source_url,
            )
        ):
            raise ValueError("CEMS products require activation, product, and version.")
        if not self.source_url.startswith("https://"):
            raise ValueError("CEMS product references must use HTTPS.")
        if self.published_at.tzinfo is None or self.published_at.utcoffset() is None:
            raise ValueError("CEMS product times must be timezone-aware.")


def cems_product_region(product: CemsDeliveredProduct) -> RegionEvidence:
    source_kind = (
        RegionSourceKind.MAPPED_IMPACT
        if product.kind in {CemsProductKind.DELINEATION, CemsProductKind.GRADING}
        else RegionSourceKind.REPORTED_PLACE
    )
    return RegionEvidence(
        evidence_id=f"cems:{product.activation_code}:{product.product_id}",
        geometry=polygon_from_geojson(product.geometry),
        source=RegionSource(
            source_id="copernicus-ems-rapid-mapping",
            source_kind=source_kind,
            publisher="Copernicus Emergency Management Service Rapid Mapping",
            reference=product.source_url,
            captured_at=product.published_at,
            attribution="Copernicus EMS Rapid Mapping",
            metadata=(
                ("activation", product.activation_code),
                ("product_id", product.product_id),
                ("product_version", product.version),
                ("product_kind", product.kind.value),
            ),
        ),
        association=AssociationStatus.CONFIRMED,
        semantic_role=f"CEMS delivered {product.kind.value}",
        observed_at=product.published_at,
        derivation_inputs=(
            product.activation_code,
            product.product_id,
            product.version,
        ),
    )


def shakemap_source_regions(
    layers: tuple[ShakeMapLayer, ...],
) -> tuple[RegionEvidence, ...]:
    """Project exact product bounds as source-backed shaking coverage."""
    regions: list[RegionEvidence] = []
    for layer in layers:
        bounds = layer.bounds
        geometry = polygon_from_geojson(
            {
                "type": "Polygon",
                "coordinates": [
                    [
                        [bounds.min_longitude, bounds.min_latitude],
                        [bounds.max_longitude, bounds.min_latitude],
                        [bounds.max_longitude, bounds.max_latitude],
                        [bounds.min_longitude, bounds.max_latitude],
                        [bounds.min_longitude, bounds.min_latitude],
                    ]
                ],
            }
        )
        regions.append(
            RegionEvidence(
                evidence_id=f"shakemap:{layer.product.product_id}:{layer.measure.value}",
                geometry=geometry,
                source=RegionSource(
                    source_id="usgs-shakemap",
                    source_kind=RegionSourceKind.MODELED_HAZARD,
                    publisher="U.S. Geological Survey",
                    reference=layer.coverage_url,
                    captured_at=layer.product.updated_at,
                    attribution="USGS ShakeMap",
                    metadata=(
                        ("event_id", layer.product.event_id),
                        ("product_id", layer.product.product_id),
                        ("product_version", layer.product.version),
                        ("measure", layer.measure.value),
                        ("coverage_sha256", layer.coverage_sha256 or "unavailable"),
                    ),
                ),
                association=AssociationStatus.CONFIRMED,
                semantic_role="USGS ShakeMap shaking coverage",
                observed_at=layer.product.updated_at,
                derivation_inputs=(layer.product.product_id, layer.product.version),
            )
        )
    return tuple(regions)


__all__ = [
    "CemsDeliveredProduct",
    "CemsProductKind",
    "cems_product_region",
    "shakemap_source_regions",
]
