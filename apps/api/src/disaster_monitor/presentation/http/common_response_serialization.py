"""Serialization from application/domain results to HTTP response models."""

from disaster_monitor.domain.disaster import (
    CycloneMapLayer,
    EventGeometry,
    SourceReference,
)
from disaster_monitor.presentation.http.schemas import (
    CycloneMapCoordinateResponse,
    CycloneMapLayerResponse,
    EventCoordinateResponse,
    EventGeometryResponse,
    SourceResponse,
)


def _event_geometry_response(
    geometry: EventGeometry | None,
) -> EventGeometryResponse | None:
    if geometry is None:
        return None
    return EventGeometryResponse(
        kind=geometry.kind.value,
        coordinates=[
            EventCoordinateResponse(
                latitude=point.latitude,
                longitude=point.longitude,
            )
            for point in geometry.coordinates
        ],
        description=geometry.description,
        source_id=geometry.source.source_id,
        estimated=geometry.estimated,
    )


def _cyclone_map_layer_response(layer: CycloneMapLayer) -> CycloneMapLayerResponse:
    return CycloneMapLayerResponse(
        layer_id=layer.layer_id,
        semantic_role=layer.semantic_role.value,
        geometry_kind=layer.geometry_kind.value,
        coordinates=[
            CycloneMapCoordinateResponse(
                latitude=point.latitude,
                longitude=point.longitude,
                valid_at=point.valid_at,
            )
            for point in layer.coordinates
        ],
        source=_source_response(layer.source),
        issued_at=layer.issued_at,
        valid_from=layer.valid_from,
        valid_to=layer.valid_to,
        storm_id=layer.storm_id,
        provisional=layer.provisional,
        limitation=layer.limitation,
        reconciliation=layer.reconciliation,
        wind_threshold=layer.wind_threshold,
        wind_threshold_unit=layer.wind_threshold_unit,
    )


def _source_response(source: SourceReference) -> SourceResponse:
    return SourceResponse(
        source_id=source.source_id,
        publisher=source.publisher,
        title=source.title,
        canonical_url=source.canonical_url,
        published_at=source.published_at,
        updated_at=source.updated_at,
        retrieved_at=source.retrieved_at,
        snapshot_id=source.snapshot_id,
    )
