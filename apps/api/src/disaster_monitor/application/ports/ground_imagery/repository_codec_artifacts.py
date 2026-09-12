"""Artifact and render-grid encoding for the ground-imagery repository codec."""

from __future__ import annotations

from typing import Any

from disaster_monitor.application.ground_imagery.models import ImageryArtifactReference
from disaster_monitor.application.ports.ground_imagery.rendering import ImageryGrid
from disaster_monitor.application.ports.ground_imagery.repository_codec_values import (
    datetime_value as _datetime,
)
from disaster_monitor.application.ports.ground_imagery.repository_codec_values import (
    integer as _integer,
)
from disaster_monitor.application.ports.ground_imagery.repository_codec_values import (
    list_value as _list,
)
from disaster_monitor.application.ports.ground_imagery.repository_codec_values import (
    mapping as _mapping,
)
from disaster_monitor.application.ports.ground_imagery.repository_codec_values import (
    mapping_value as _mapping_value,
)
from disaster_monitor.application.ports.ground_imagery.repository_codec_values import (
    number as _number,
)
from disaster_monitor.application.ports.ground_imagery.repository_codec_values import (
    string as _string,
)
from disaster_monitor.application.ports.ground_imagery.repository_codec_values import (
    string_value as _string_value,
)
from disaster_monitor.domain.imagery.observations import Sensor, TemporalRole


def artifact_document(artifact: ImageryArtifactReference) -> dict[str, Any]:
    grid = artifact.grid
    return {
        "artifact_id": artifact.artifact_id,
        "selection_id": artifact.selection_id,
        "sensor": artifact.sensor.value,
        "role": artifact.role.value,
        "output_kind": artifact.output_kind,
        "content_type": artifact.content_type,
        "storage_key": artifact.storage_key,
        "byte_count": artifact.byte_count,
        "sha256": artifact.sha256,
        "source_product_ids": list(artifact.source_product_ids),
        "grid": {
            "crs": grid.crs,
            "min_x": grid.min_x,
            "min_y": grid.min_y,
            "max_x": grid.max_x,
            "max_y": grid.max_y,
            "pixel_size_m": grid.pixel_size_m,
            "width": grid.width,
            "height": grid.height,
            "resolution_label": grid.resolution_label,
        },
        "created_at": artifact.created_at.isoformat(),
    }


def artifact_from_document(document: object) -> ImageryArtifactReference:
    value = _mapping_value(document)
    return ImageryArtifactReference(
        artifact_id=_string(value, "artifact_id"),
        selection_id=_string(value, "selection_id"),
        sensor=Sensor(_string(value, "sensor")),
        role=TemporalRole(_string(value, "role")),
        output_kind=_string(value, "output_kind"),
        content_type=_string(value, "content_type"),
        storage_key=_string(value, "storage_key"),
        byte_count=_integer(value, "byte_count"),
        sha256=_string(value, "sha256"),
        source_product_ids=tuple(
            _string_value(item, "source_product_ids")
            for item in _list(value, "source_product_ids")
        ),
        grid=grid_from_document(_mapping(value, "grid")),
        created_at=_datetime(value, "created_at"),
    )


def grid_from_document(document: dict[str, Any]) -> ImageryGrid:
    return ImageryGrid(
        crs=_string(document, "crs"),
        min_x=_number(document, "min_x"),
        min_y=_number(document, "min_y"),
        max_x=_number(document, "max_x"),
        max_y=_number(document, "max_y"),
        pixel_size_m=_number(document, "pixel_size_m"),
        width=_integer(document, "width"),
        height=_integer(document, "height"),
        resolution_label=_string(document, "resolution_label"),
    )
