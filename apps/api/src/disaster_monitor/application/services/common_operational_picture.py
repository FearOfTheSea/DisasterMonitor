"""Build renderer-independent, provenance-complete COP artifacts."""

from datetime import UTC, datetime
from hashlib import sha256

from disaster_monitor.application.services.multimodal_geometry import (
    MultimodalGeometryPolicy,
)
from disaster_monitor.domain.multimodal import (
    AnalyticalMapFeature,
    AnalyticalMapLayer,
    CommonOperationalPicture,
    CopStatus,
    DamageLevel,
    MultimodalEvidenceState,
    SourceMapFeature,
    SourceMapLayer,
    VisualObservationKind,
    VisualObservationStatus,
)


class CommonOperationalPictureBuilder:
    """Generate only validated overlays from admitted, associated artifacts."""

    def __init__(self, geometry_policy: MultimodalGeometryPolicy | None = None) -> None:
        self._geometry = geometry_policy or MultimodalGeometryPolicy()

    def build(
        self,
        state: MultimodalEvidenceState,
        *,
        created_at: datetime,
        source_features: tuple[SourceMapFeature, ...] = (),
    ) -> CommonOperationalPicture | None:
        created = (
            created_at
            if created_at.tzinfo is not None
            else created_at.replace(tzinfo=UTC)
        )
        assets = {asset.asset_id: asset for asset in state.assets}
        analytical_features: list[AnalyticalMapFeature] = []
        for observation in state.observations:
            damage_level = observation.damage_level
            if (
                observation.kind != VisualObservationKind.DAMAGE_ASSESSMENT
                or observation.status != VisualObservationStatus.PRODUCED
                or damage_level is None
                or damage_level == DamageLevel.UNKNOWN
            ):
                continue
            asset = assets.get(observation.asset_id)
            if asset is None or asset.footprint is None:
                continue
            self._geometry.validate(asset.footprint)
            material = "|".join(
                (
                    state.physical_event_id,
                    asset.asset_id,
                    observation.observation_id,
                    damage_level.value,
                )
            )
            analytical_features.append(
                AnalyticalMapFeature(
                    feature_id=(
                        f"map-feature:{sha256(material.encode('utf-8')).hexdigest()[:24]}"
                    ),
                    physical_event_id=state.physical_event_id,
                    source_asset_ids=(asset.asset_id,),
                    visual_observation_ids=(observation.observation_id,),
                    created_at=created,
                    updated_at=None,
                    semantic_kind=f"visible_damage:{damage_level.value}",
                    geometry=asset.footprint,
                    attribution=(
                        f"{asset.source.attribution}; analytical visual overlay by "
                        f"{observation.configuration.model_id}"
                    ),
                    status=CopStatus.CURRENT,
                    uncertainty=observation.uncertainty,
                    confidence=observation.confidence,
                )
            )
        layers: list[SourceMapLayer | AnalyticalMapLayer] = []
        if source_features:
            for feature in source_features:
                self._geometry.validate(feature.geometry)
                if not set(feature.source_asset_ids).issubset(assets):
                    raise ValueError(
                        "Source map feature provenance must reference admitted assets."
                    )
            layers.append(
                SourceMapLayer(
                    layer_id=_layer_id("source", state, source_features),
                    physical_event_id=state.physical_event_id,
                    title="Source-supplied geometry",
                    semantic_kind="source_geometry",
                    features=source_features,
                    source_ids=tuple(
                        sorted({feature.source_id for feature in source_features})
                    ),
                    source_asset_ids=_source_asset_ids(source_features),
                    created_at=created,
                    updated_at=_updated_at(source_features, created),
                    status=_layer_status(source_features),
                    uncertainty=(
                        "Source status and uncertainty are retained on every feature."
                    ),
                    attribution=(
                        "Source-supplied geometry; inspect each feature attribution."
                    ),
                )
            )
        if analytical_features:
            features = tuple(
                sorted(analytical_features, key=lambda item: item.feature_id)
            )
            layers.append(
                AnalyticalMapLayer(
                    layer_id=_layer_id("analytical", state, features),
                    physical_event_id=state.physical_event_id,
                    title="Analytical visible-damage overlay",
                    semantic_kind="visible_damage_assessment",
                    features=features,
                    source_asset_ids=_source_asset_ids(features),
                    visual_observation_ids=tuple(
                        sorted(
                            {
                                observation_id
                                for feature in features
                                for observation_id in feature.visual_observation_ids
                            }
                        )
                    ),
                    created_at=created,
                    updated_at=_updated_at(features, created),
                    status=_layer_status(features),
                    uncertainty=(
                        "Analytical visual estimates only; inspect feature confidence "
                        "and uncertainty."
                    ),
                    attribution=(
                        "AI-generated analytical geometry; not an official boundary "
                        "or alert."
                    ),
                )
            )
        if not layers:
            return None
        material = "|".join(
            (
                state.state_version,
                *(layer.layer_id for layer in layers),
            )
        )
        cop_id = f"cop:{sha256(material.encode('utf-8')).hexdigest()[:24]}"
        return CommonOperationalPicture(
            cop_id=cop_id,
            physical_event_id=state.physical_event_id,
            multimodal_state_version=state.state_version,
            created_at=created,
            updated_at=created,
            status=CopStatus.CURRENT,
            layers=tuple(layers),
        )


def _layer_id(
    kind: str,
    state: MultimodalEvidenceState,
    features: tuple[SourceMapFeature | AnalyticalMapFeature, ...],
) -> str:
    material = "|".join(
        (kind, state.physical_event_id, *(feature.feature_id for feature in features))
    )
    return f"map-layer:{sha256(material.encode('utf-8')).hexdigest()[:24]}"


def _source_asset_ids(
    features: tuple[SourceMapFeature | AnalyticalMapFeature, ...],
) -> tuple[str, ...]:
    return tuple(
        sorted(
            {asset_id for feature in features for asset_id in feature.source_asset_ids}
        )
    )


def _updated_at(
    features: tuple[SourceMapFeature | AnalyticalMapFeature, ...],
    created_at: datetime,
) -> datetime:
    return max(
        (feature.updated_at or feature.created_at for feature in features),
        default=created_at,
    )


def _layer_status(
    features: tuple[SourceMapFeature | AnalyticalMapFeature, ...],
) -> CopStatus:
    statuses = {feature.status for feature in features}
    if CopStatus.PREVIEW_ONLY in statuses:
        return CopStatus.PREVIEW_ONLY
    if CopStatus.STALE in statuses:
        return CopStatus.STALE
    return CopStatus.CURRENT
