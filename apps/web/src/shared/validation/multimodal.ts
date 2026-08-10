import type {
  AnalyticalMapFeature,
  AssetEventAssociation,
  CommonOperationalPicture,
  CopGeometry,
  CopLayer,
  MultimodalAsset,
  MultimodalEvidenceState,
  SourceMapFeature,
  VisualAnalysisConfiguration,
  VisualObservation,
} from '@/shared/types/assistant';

type UnknownObject = Record<string, unknown>;

export function isMultimodalEvidenceState(
  value: unknown,
): value is MultimodalEvidenceState {
  if (!isObject(value)) return false;
  return (
    strings(value, [
      'state_version',
      'evidence_world_state_version',
      'physical_event_id',
      'evaluated_at',
    ]) &&
    Array.isArray(value.assets) &&
    value.assets.every(isAsset) &&
    Array.isArray(value.associations) &&
    value.associations.every(isAssociation) &&
    Array.isArray(value.observations) &&
    value.observations.every(isObservation) &&
    referencesStayWithinState(value as MultimodalEvidenceState)
  );
}

export function isCommonOperationalPicture(
  value: unknown,
): value is CommonOperationalPicture {
  if (!isObject(value)) return false;
  if (
    !strings(value, [
      'cop_id',
      'physical_event_id',
      'multimodal_state_version',
      'created_at',
      'updated_at',
      'status',
    ]) ||
    !Array.isArray(value.layers) ||
    value.layers.length === 0
  ) {
    return false;
  }
  return value.layers.every(
    (layer) => isLayer(layer) && layer.physical_event_id === value.physical_event_id,
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

function isAsset(value: unknown): value is MultimodalAsset {
  if (!isObject(value) || !isObject(value.source)) return false;
  return (
    strings(value, [
      'asset_id',
      'retrieved_at',
      'modality',
      'media_type',
      'content_sha256',
      'capture_role',
      'eligibility',
    ]) &&
    strings(value.source, ['source_id', 'attribution']) &&
    typeof value.byte_length === 'number' &&
    value.byte_length > 0 &&
    stringArray(value.parent_asset_ids) &&
    stringArray(value.eligibility_reasons) &&
    (value.footprint === undefined ||
      value.footprint === null ||
      isGeometry(value.footprint))
  );
}

function isAssociation(value: unknown): value is AssetEventAssociation {
  return (
    isObject(value) &&
    strings(value, [
      'association_id',
      'asset_id',
      'physical_event_id',
      'status',
      'detail',
    ]) &&
    stringArray(value.rule_ids)
  );
}

function isObservation(value: unknown): value is VisualObservation {
  if (!isObject(value) || !isObject(value.configuration)) return false;
  return (
    strings(value, [
      'observation_id',
      'asset_id',
      'association_id',
      'physical_event_id',
      'kind',
      'status',
      'uncertainty',
      'created_at',
    ]) &&
    value.modality === 'image' &&
    value.truth_status === 'analytical' &&
    optionalConfidence(value.confidence) &&
    stringArray(value.visual_cues) &&
    stringArray(value.safety_rule_ids) &&
    isConfiguration(value.configuration)
  );
}

function isConfiguration(value: UnknownObject): value is VisualAnalysisConfiguration {
  return (
    strings(value, [
      'model_id',
      'adapter_version',
      'analysis_version',
      'prompt_version',
      'preprocessing_version',
    ]) &&
    typeof value.maximum_output_tokens === 'number' &&
    value.maximum_output_tokens > 0 &&
    typeof value.temperature === 'number' &&
    typeof value.seed === 'number'
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

function isLayer(value: unknown): value is CopLayer {
  if (
    !isObject(value) ||
    !strings(value, [
      'layer_id',
      'physical_event_id',
      'title',
      'semantic_kind',
      'created_at',
      'updated_at',
      'status',
      'uncertainty',
      'attribution',
    ]) ||
    !Array.isArray(value.features) ||
    value.features.length === 0
  ) {
    return false;
  }
  if (value.layer_type === 'source') {
    return (
      stringArray(value.source_ids) &&
      value.source_ids.length > 0 &&
      stringArray(value.source_asset_ids) &&
      value.source_asset_ids.length > 0 &&
      value.features.every(
        (feature) =>
          isSourceFeature(feature) &&
          feature.physical_event_id === value.physical_event_id,
      ) &&
      sameStrings(
        value.source_ids,
        value.features.map((feature) => feature.source_id),
      ) &&
      sameStrings(
        value.source_asset_ids,
        value.features.flatMap((feature) => feature.source_asset_ids),
      )
    );
  }
  if (value.layer_type === 'analytical') {
    return (
      stringArray(value.source_asset_ids) &&
      value.source_asset_ids.length > 0 &&
      stringArray(value.visual_observation_ids) &&
      value.visual_observation_ids.length > 0 &&
      value.features.every(
        (feature) =>
          isAnalyticalFeature(feature) &&
          feature.physical_event_id === value.physical_event_id,
      ) &&
      sameStrings(
        value.source_asset_ids,
        value.features.flatMap((feature) => feature.source_asset_ids),
      ) &&
      sameStrings(
        value.visual_observation_ids,
        value.features.flatMap((feature) => feature.visual_observation_ids),
      )
    );
  }
  return false;
}

function isSourceFeature(value: unknown): value is SourceMapFeature {
  if (!isFeatureBase(value) || value.feature_type !== 'source') return false;
  const sourceMatches =
    (value.source_authority === 'official' && value.authority === 'official_source') ||
    (value.source_authority === 'source_supplied' &&
      value.authority === 'source_supplied');
  return (
    typeof value.source_id === 'string' && value.source_id.length > 0 && sourceMatches
  );
}

function isAnalyticalFeature(value: unknown): value is AnalyticalMapFeature {
  return (
    isFeatureBase(value) &&
    value.feature_type === 'analytical' &&
    value.authority === 'analytical_generated' &&
    stringArray(value.visual_observation_ids) &&
    value.visual_observation_ids.length > 0 &&
    optionalConfidence(value.confidence)
  );
}

function isFeatureBase(value: unknown): value is UnknownObject & {
  source_asset_ids: string[];
  geometry: CopGeometry;
} {
  return (
    isObject(value) &&
    strings(value, [
      'feature_id',
      'physical_event_id',
      'created_at',
      'semantic_kind',
      'attribution',
      'status',
      'uncertainty',
    ]) &&
    stringArray(value.source_asset_ids) &&
    value.source_asset_ids.length > 0 &&
    isGeometry(value.geometry)
  );
}

function isGeometry(value: unknown): value is CopGeometry {
  if (!isObject(value) || value.crs !== 'EPSG:4326') return false;
  if (value.type === 'Point') return isCoordinate(value.coordinates);
  if (value.type === 'LineString') {
    return (
      Array.isArray(value.coordinates) &&
      value.coordinates.length >= 2 &&
      value.coordinates.length <= 4_096 &&
      value.coordinates.every(isCoordinate)
    );
  }
  if (value.type === 'Polygon') {
    return isPolygonCoordinates(value.coordinates);
  }
  return false;
}

function isCoordinate(value: unknown): value is [number, number] {
  return (
    Array.isArray(value) &&
    value.length === 2 &&
    value.every((item) => typeof item === 'number' && Number.isFinite(item)) &&
    value[0] >= -180 &&
    value[0] <= 180 &&
    value[1] >= -90 &&
    value[1] <= 90
  );
}

function isPolygonCoordinates(value: unknown): value is [number, number][][] {
  if (!Array.isArray(value) || value.length === 0 || value.length > 8) return false;
  if (
    value.some(
      (ring) =>
        !Array.isArray(ring) ||
        ring.length < 4 ||
        !ring.every(isCoordinate) ||
        ring[0][0] !== ring[ring.length - 1][0] ||
        ring[0][1] !== ring[ring.length - 1][1],
    )
  ) {
    return false;
  }
  const rings = value as [number, number][][];
  if (
    rings.reduce((total, ring) => total + ring.length, 0) > 4_096 ||
    rings.some((ring) => Math.abs(signedArea(ring)) < 1e-12 || selfIntersects(ring))
  ) {
    return false;
  }
  const [exterior, ...holes] = rings;
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
      if (second === first + 1 || (first === 0 && second === lastSegment)) {
        continue;
      }
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

function optionalConfidence(value: unknown): boolean {
  return (
    value === undefined ||
    value === null ||
    (typeof value === 'number' && Number.isFinite(value) && value >= 0 && value <= 1)
  );
}

function strings(value: UnknownObject, names: string[]): boolean {
  return names.every(
    (name) => typeof value[name] === 'string' && value[name].length > 0,
  );
}

function stringArray(value: unknown): value is string[] {
  return Array.isArray(value) && value.every((item) => typeof item === 'string');
}

function sameStrings(left: string[], right: string[]): boolean {
  return (
    new Set(left).size === new Set(right).size &&
    [...new Set(left)].every((item) => new Set(right).has(item))
  );
}

function isObject(value: unknown): value is UnknownObject {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}
