import { matchesApiSchema } from '@/shared/api/generated/assistant';
import type {
  AnalyticalMapFeature,
  CommonOperationalPicture,
  CopGeometry,
  CopLayer,
  MultimodalEvidenceState,
  SourceMapFeature,
} from '@/shared/types/assistant';

export function isMultimodalEvidenceState(
  value: unknown,
): value is MultimodalEvidenceState {
  if (!matchesApiSchema('MultimodalStateResponse', value)) return false;
  const state = value as MultimodalEvidenceState;
  return (
    Array.isArray(state.assets) &&
    Array.isArray(state.associations) &&
    Array.isArray(state.observations) &&
    state.assets.every(
      (asset) =>
        nonEmpty(
          asset.asset_id,
          asset.retrieved_at,
          asset.modality,
          asset.media_type,
          asset.content_sha256,
          asset.capture_role,
          asset.eligibility,
          asset.source.source_id,
          asset.source.attribution,
        ) && asset.byte_length > 0,
    ) &&
    state.associations.every((association) =>
      nonEmpty(
        association.association_id,
        association.asset_id,
        association.physical_event_id,
        association.status,
        association.detail,
      ),
    ) &&
    state.observations.every(
      (observation) =>
        observation.modality === 'image' &&
        observation.truth_status === 'analytical' &&
        nonEmpty(
          observation.observation_id,
          observation.asset_id,
          observation.association_id,
          observation.physical_event_id,
          observation.kind,
          observation.status,
          observation.uncertainty,
          observation.created_at,
          observation.configuration.model_id,
          observation.configuration.adapter_version,
          observation.configuration.analysis_version,
          observation.configuration.prompt_version,
          observation.configuration.preprocessing_version,
        ) &&
        observation.configuration.maximum_output_tokens > 0,
    ) &&
    referencesStayWithinState(state)
  );
}

export function isCommonOperationalPicture(
  value: unknown,
): value is CommonOperationalPicture {
  if (!matchesApiSchema('CommonOperationalPictureResponse', value)) return false;
  const cop = value as CommonOperationalPicture;
  return (
    cop.layers.length > 0 &&
    cop.layers.every(
      (layer) =>
        layer.physical_event_id === cop.physical_event_id && layerIsConsistent(layer),
    )
  );
}

export function copMatchesMultimodalState(
  cop: CommonOperationalPicture,
  state: MultimodalEvidenceState,
): boolean {
  if (
    cop.multimodal_state_version !== state.state_version ||
    cop.physical_event_id !== state.physical_event_id
  ) {
    return false;
  }
  const assets = new Set(state.assets.map((item) => item.asset_id));
  const observations = new Set(state.observations.map((item) => item.observation_id));
  return cop.layers.every((layer) =>
    layer.features.every(
      (feature) =>
        feature.source_asset_ids.every((id) => assets.has(id)) &&
        (feature.feature_type === 'source' ||
          feature.visual_observation_ids.every((id) => observations.has(id))),
    ),
  );
}

function referencesStayWithinState(state: MultimodalEvidenceState): boolean {
  const assets = new Set(state.assets.map((item) => item.asset_id));
  const associations = new Set(state.associations.map((item) => item.association_id));
  return (
    state.associations.every(
      (item) =>
        assets.has(item.asset_id) && item.physical_event_id === state.physical_event_id,
    ) &&
    state.observations.every(
      (item) =>
        assets.has(item.asset_id) &&
        associations.has(item.association_id) &&
        item.physical_event_id === state.physical_event_id,
    )
  );
}

function layerIsConsistent(layer: CopLayer): boolean {
  if (
    layer.features.length === 0 ||
    !nonEmpty(
      layer.layer_id,
      layer.physical_event_id,
      layer.title,
      layer.semantic_kind,
      layer.created_at,
      layer.updated_at,
      layer.status,
      layer.uncertainty,
      layer.attribution,
    )
  ) {
    return false;
  }
  if (layer.layer_type === 'source') {
    return (
      layer.source_ids.length > 0 &&
      layer.source_asset_ids.length > 0 &&
      layer.features.every(
        (feature) =>
          sourceFeatureIsConsistent(feature) &&
          feature.physical_event_id === layer.physical_event_id,
      ) &&
      sameStrings(
        layer.source_ids,
        layer.features.map((feature) => feature.source_id),
      ) &&
      sameStrings(
        layer.source_asset_ids,
        layer.features.flatMap((feature) => feature.source_asset_ids),
      )
    );
  }
  return (
    layer.source_asset_ids.length > 0 &&
    layer.visual_observation_ids.length > 0 &&
    layer.features.every(
      (feature) =>
        analyticalFeatureIsConsistent(feature) &&
        feature.physical_event_id === layer.physical_event_id,
    ) &&
    sameStrings(
      layer.source_asset_ids,
      layer.features.flatMap((feature) => feature.source_asset_ids),
    ) &&
    sameStrings(
      layer.visual_observation_ids,
      layer.features.flatMap((feature) => feature.visual_observation_ids),
    )
  );
}

function sourceFeatureIsConsistent(feature: SourceMapFeature): boolean {
  const authorityMatches =
    (feature.source_authority === 'official' &&
      feature.authority === 'official_source') ||
    (feature.source_authority === 'source_supplied' &&
      feature.authority === 'source_supplied');
  return (
    authorityMatches && nonEmpty(feature.source_id) && featureBaseIsConsistent(feature)
  );
}

function analyticalFeatureIsConsistent(feature: AnalyticalMapFeature): boolean {
  return (
    feature.authority === 'analytical_generated' &&
    feature.visual_observation_ids.length > 0 &&
    featureBaseIsConsistent(feature)
  );
}

function featureBaseIsConsistent(
  feature: SourceMapFeature | AnalyticalMapFeature,
): boolean {
  return (
    nonEmpty(
      feature.feature_id,
      feature.physical_event_id,
      feature.created_at,
      feature.semantic_kind,
      feature.attribution,
      feature.status,
      feature.uncertainty,
    ) &&
    feature.source_asset_ids.length > 0 &&
    geometryIsValid(feature.geometry)
  );
}

function geometryIsValid(value: CopGeometry): boolean {
  if (value.crs !== 'EPSG:4326') return false;
  if (value.type === 'Point') return isCoordinate(value.coordinates);
  if (value.type === 'LineString') {
    return (
      value.coordinates.length >= 2 &&
      value.coordinates.length <= 4_096 &&
      value.coordinates.every(isCoordinate)
    );
  }
  return isPolygonCoordinates(value.coordinates);
}

function isCoordinate(value: [number, number]): boolean {
  return (
    value.every(Number.isFinite) &&
    value[0] >= -180 &&
    value[0] <= 180 &&
    value[1] >= -90 &&
    value[1] <= 90
  );
}

function isPolygonCoordinates(value: [number, number][][]): boolean {
  if (value.length === 0 || value.length > 8) return false;
  if (
    value.some(
      (ring) =>
        ring.length < 4 ||
        !ring.every(isCoordinate) ||
        ring[0][0] !== ring[ring.length - 1][0] ||
        ring[0][1] !== ring[ring.length - 1][1],
    )
  ) {
    return false;
  }
  if (
    value.reduce((total, ring) => total + ring.length, 0) > 4_096 ||
    value.some((ring) => Math.abs(signedArea(ring)) < 1e-12 || selfIntersects(ring))
  ) {
    return false;
  }
  const [exterior, ...holes] = value;
  if (
    holes.some(
      (hole) =>
        ringsIntersect(exterior, hole) ||
        hole.slice(0, -1).some((point) => !pointInRing(point, exterior)),
    )
  ) {
    return false;
  }
  return !holes.some((first, index) =>
    holes
      .slice(index + 1)
      .some(
        (second) =>
          ringsIntersect(first, second) ||
          pointInRing(first[0], second) ||
          pointInRing(second[0], first),
      ),
  );
}

function signedArea(ring: [number, number][]): number {
  return (
    ring
      .slice(0, -1)
      .reduce(
        (area, point, index) =>
          area + point[0] * ring[index + 1][1] - ring[index + 1][0] * point[1],
        0,
      ) / 2
  );
}

function orientation(
  first: [number, number],
  second: [number, number],
  third: [number, number],
): number {
  return (
    (second[0] - first[0]) * (third[1] - first[1]) -
    (second[1] - first[1]) * (third[0] - first[0])
  );
}

function onSegment(
  first: [number, number],
  second: [number, number],
  point: [number, number],
): boolean {
  return (
    point[0] >= Math.min(first[0], second[0]) &&
    point[0] <= Math.max(first[0], second[0]) &&
    point[1] >= Math.min(first[1], second[1]) &&
    point[1] <= Math.max(first[1], second[1]) &&
    Math.abs(orientation(first, second, point)) < 1e-12
  );
}

function segmentsIntersect(
  first: [number, number],
  second: [number, number],
  third: [number, number],
  fourth: [number, number],
): boolean {
  const values = [
    orientation(first, second, third),
    orientation(first, second, fourth),
    orientation(third, fourth, first),
    orientation(third, fourth, second),
  ];
  if (values[0] * values[1] < 0 && values[2] * values[3] < 0) return true;
  return (
    (Math.abs(values[0]) < 1e-12 && onSegment(first, second, third)) ||
    (Math.abs(values[1]) < 1e-12 && onSegment(first, second, fourth)) ||
    (Math.abs(values[2]) < 1e-12 && onSegment(third, fourth, first)) ||
    (Math.abs(values[3]) < 1e-12 && onSegment(third, fourth, second))
  );
}

function selfIntersects(ring: [number, number][]): boolean {
  const lastSegment = ring.length - 2;
  for (let first = 0; first < ring.length - 1; first += 1) {
    for (let second = first + 1; second < ring.length - 1; second += 1) {
      if (second === first + 1 || (first === 0 && second === lastSegment)) continue;
      if (
        segmentsIntersect(ring[first], ring[first + 1], ring[second], ring[second + 1])
      ) {
        return true;
      }
    }
  }
  return false;
}

function ringsIntersect(
  first: [number, number][],
  second: [number, number][],
): boolean {
  return first
    .slice(0, -1)
    .some((point, firstIndex) =>
      second
        .slice(0, -1)
        .some((other, secondIndex) =>
          segmentsIntersect(
            point,
            first[firstIndex + 1],
            other,
            second[secondIndex + 1],
          ),
        ),
    );
}

function pointInRing(point: [number, number], ring: [number, number][]): boolean {
  if (
    ring.slice(0, -1).some((first, index) => onSegment(first, ring[index + 1], point))
  ) {
    return false;
  }
  let inside = false;
  for (let index = 0; index < ring.length - 1; index += 1) {
    const first = ring[index];
    const second = ring[index + 1];
    if (first[1] > point[1] === second[1] > point[1]) continue;
    const boundary =
      first[0] +
      ((point[1] - first[1]) * (second[0] - first[0])) / (second[1] - first[1]);
    if (point[0] < boundary) inside = !inside;
  }
  return inside;
}

function nonEmpty(...values: string[]): boolean {
  return values.every((value) => value.trim().length > 0);
}

function sameStrings(left: string[], right: string[]): boolean {
  return (
    new Set(left).size === new Set(right).size &&
    [...new Set(left)].every((item) => new Set(right).has(item))
  );
}
