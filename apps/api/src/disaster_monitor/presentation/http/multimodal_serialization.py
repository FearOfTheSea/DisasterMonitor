"""Translate domain multimodal artifacts into stable HTTP DTOs."""

from typing import Literal

from disaster_monitor.domain.multimodal import (
    AnalyticalMapFeature,
    AnalyticalMapLayer,
    CommonOperationalPicture,
    GeoLineString,
    GeoPoint,
    GeoPolygon,
    MapFeatureAuthority,
    MapGeometry,
    MultimodalEvidenceState,
    SourceMapFeature,
    SourceMapLayer,
)
from disaster_monitor.presentation.http.multimodal_schemas import (
    AnalyticalMapFeatureResponse,
    AnalyticalMapLayerResponse,
    AssetEventAssociationResponse,
    CommonOperationalPictureResponse,
    GeometryResponse,
    LineStringGeometryResponse,
    MultimodalAssetResponse,
    MultimodalSourceResponse,
    MultimodalStateResponse,
    PointGeometryResponse,
    PolygonGeometryResponse,
    SourceMapFeatureResponse,
    SourceMapLayerResponse,
    VisualAnalysisConfigurationResponse,
    VisualObservationResponse,
)


def multimodal_state_response(
    state: MultimodalEvidenceState | None,
) -> MultimodalStateResponse | None:
    if state is None:
        return None
    return MultimodalStateResponse(
        state_version=state.state_version,
        evidence_world_state_version=state.evidence_world_state_version,
        physical_event_id=state.physical_event_id,
        assets=[
            MultimodalAssetResponse(
                asset_id=asset.asset_id,
                source=MultimodalSourceResponse(
                    source_id=asset.source.source_id,
                    attribution=asset.source.attribution,
                    canonical_url=asset.source.canonical_url,
                    dataset_id=asset.source.dataset_id,
                    license_name=asset.source.license_name,
                ),
                retrieved_at=asset.retrieved_at,
                captured_at=asset.captured_at,
                modality=asset.modality.value,
                media_type=asset.media_type,
                content_sha256=asset.content_sha256,
                byte_length=asset.byte_length,
                width=asset.width,
                height=asset.height,
                footprint=(
                    None
                    if asset.footprint is None
                    else _polygon_geometry(asset.footprint)
                ),
                declared_disaster=(
                    asset.declared_disaster.value if asset.declared_disaster else None
                ),
                declared_country_code=asset.declared_country_code,
                capture_role=asset.capture_role.value,
                processing_level=asset.processing_level,
                parent_asset_ids=list(asset.parent_asset_ids),
                event_id_hint=asset.event_id_hint,
                eligibility=asset.eligibility.value,
                eligibility_reasons=list(asset.eligibility_reasons),
            )
            for asset in state.assets
        ],
        associations=[
            AssetEventAssociationResponse(
                association_id=item.association_id,
                asset_id=item.asset_id,
                physical_event_id=item.physical_event_id,
                status=item.status.value,
                geography_match=item.geography_match,
                time_match=item.time_match,
                disaster_match=item.disaster_match,
                country_match=item.country_match,
                event_id_match=item.event_id_match,
                distance_km=item.distance_km,
                time_delta_seconds=item.time_delta_seconds,
                rule_ids=list(item.rule_ids),
                detail=item.detail,
            )
            for item in state.associations
        ],
        observations=[
            VisualObservationResponse(
                observation_id=item.observation_id,
                asset_id=item.asset_id,
                association_id=item.association_id,
                physical_event_id=item.physical_event_id,
                modality="image",
                truth_status="analytical",
                kind=item.kind.value,
                status=item.status.value,
                damage_level=(item.damage_level.value if item.damage_level else None),
                question=item.question,
                answer=item.answer,
                answerable=item.answerable,
                confidence=item.confidence,
                uncertainty=item.uncertainty,
                visual_cues=list(item.visual_cues),
                configuration=VisualAnalysisConfigurationResponse(
                    model_id=item.configuration.model_id,
                    model_digest=item.configuration.model_digest,
                    adapter_version=item.configuration.adapter_version,
                    analysis_version=item.configuration.analysis_version,
                    prompt_version=item.configuration.prompt_version,
                    preprocessing_version=item.configuration.preprocessing_version,
                    maximum_output_tokens=(item.configuration.maximum_output_tokens),
                    temperature=item.configuration.temperature,
                    seed=item.configuration.seed,
                ),
                created_at=item.created_at,
                safety_rule_ids=list(item.safety_rule_ids),
            )
            for item in state.observations
        ],
        evaluated_at=state.evaluated_at,
    )


def cop_response(
    cop: CommonOperationalPicture | None,
) -> CommonOperationalPictureResponse | None:
    if cop is None:
        return None
    layers = [
        _source_layer(layer)
        if isinstance(layer, SourceMapLayer)
        else _analytical_layer(layer)
        for layer in cop.layers
    ]
    return CommonOperationalPictureResponse(
        cop_id=cop.cop_id,
        physical_event_id=cop.physical_event_id,
        multimodal_state_version=cop.multimodal_state_version,
        created_at=cop.created_at,
        updated_at=cop.updated_at,
        status=cop.status.value,
        layers=layers,
    )


def _source_layer(layer: SourceMapLayer) -> SourceMapLayerResponse:
    return SourceMapLayerResponse(
        layer_type="source",
        layer_id=layer.layer_id,
        physical_event_id=layer.physical_event_id,
        title=layer.title,
        semantic_kind=layer.semantic_kind,
        features=[_source_feature(feature) for feature in layer.features],
        source_ids=list(layer.source_ids),
        source_asset_ids=list(layer.source_asset_ids),
        created_at=layer.created_at,
        updated_at=layer.updated_at,
        status=layer.status.value,
        uncertainty=layer.uncertainty,
        attribution=layer.attribution,
    )


def _analytical_layer(layer: AnalyticalMapLayer) -> AnalyticalMapLayerResponse:
    return AnalyticalMapLayerResponse(
        layer_type="analytical",
        layer_id=layer.layer_id,
        physical_event_id=layer.physical_event_id,
        title=layer.title,
        semantic_kind=layer.semantic_kind,
        features=[_analytical_feature(feature) for feature in layer.features],
        source_asset_ids=list(layer.source_asset_ids),
        visual_observation_ids=list(layer.visual_observation_ids),
        created_at=layer.created_at,
        updated_at=layer.updated_at,
        status=layer.status.value,
        uncertainty=layer.uncertainty,
        attribution=layer.attribution,
    )


def _source_feature(feature: SourceMapFeature) -> SourceMapFeatureResponse:
    authority: Literal["official_source", "source_supplied"] = (
        "official_source"
        if feature.authority == MapFeatureAuthority.OFFICIAL_SOURCE
        else "source_supplied"
    )
    return SourceMapFeatureResponse(
        feature_type="source",
        feature_id=feature.feature_id,
        physical_event_id=feature.physical_event_id,
        source_id=feature.source_id,
        source_asset_ids=list(feature.source_asset_ids),
        created_at=feature.created_at,
        updated_at=feature.updated_at,
        semantic_kind=feature.semantic_kind,
        geometry=_geometry(feature.geometry),
        attribution=feature.attribution,
        status=feature.status.value,
        uncertainty=feature.uncertainty,
        authority=authority,
        source_authority=feature.source_authority.value,
    )


def _analytical_feature(
    feature: AnalyticalMapFeature,
) -> AnalyticalMapFeatureResponse:
    return AnalyticalMapFeatureResponse(
        feature_type="analytical",
        feature_id=feature.feature_id,
        physical_event_id=feature.physical_event_id,
        source_asset_ids=list(feature.source_asset_ids),
        visual_observation_ids=list(feature.visual_observation_ids),
        created_at=feature.created_at,
        updated_at=feature.updated_at,
        semantic_kind=feature.semantic_kind,
        geometry=_geometry(feature.geometry),
        attribution=feature.attribution,
        status=feature.status.value,
        uncertainty=feature.uncertainty,
        confidence=feature.confidence,
        authority="analytical_generated",
    )


def _geometry(geometry: MapGeometry) -> GeometryResponse:
    if isinstance(geometry, GeoPoint):
        return PointGeometryResponse(
            type="Point",
            coordinates=(geometry.longitude, geometry.latitude),
            crs="EPSG:4326",
        )
    if isinstance(geometry, GeoLineString):
        return LineStringGeometryResponse(
            type="LineString",
            coordinates=[(item.longitude, item.latitude) for item in geometry.points],
            crs="EPSG:4326",
        )
    if isinstance(geometry, GeoPolygon):
        return PolygonGeometryResponse(
            type="Polygon",
            coordinates=[
                [(item.longitude, item.latitude) for item in ring]
                for ring in geometry.rings
            ],
            crs="EPSG:4326",
        )
    raise TypeError("Unsupported COP geometry type.")


def _polygon_geometry(geometry: GeoPolygon) -> PolygonGeometryResponse:
    return PolygonGeometryResponse(
        type="Polygon",
        coordinates=[
            [(item.longitude, item.latitude) for item in ring]
            for ring in geometry.rings
        ],
        crs="EPSG:4326",
    )
