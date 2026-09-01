import {
  MAP_LAYER_REGISTRY,
  type MapLayerId,
} from '@/features/map/model/mapLayerRegistry';
import {
  MAP_TIME_WINDOWS,
  type MapLayerState,
  type MapTimeWindow,
} from '@/features/map/model/mapLayerState';
import {
  REGIONAL_PRESET_IDS,
  regionalPreset,
  type RegionalPresetId,
  type RegionalSelection,
} from '@/features/map/model/regionalPresets';
import {
  SATELLITE_IMAGERY_SOURCES,
  validObservationTime,
  type SatelliteSourceId,
} from '@/features/map/model/satelliteImagery';
import type { MapView } from '@/shared/types/assistant';

export type MapUrlState = {
  view: MapView;
  regionalPreset: RegionalSelection;
  selectedIncidentId?: string;
  layerState: MapLayerState;
  satelliteSourceId: SatelliteSourceId;
  satelliteObservationTime?: string;
};

const LAYER_IDS = new Set(MAP_LAYER_REGISTRY.map((layer) => layer.id));
const TIME_WINDOWS = new Set<string>(MAP_TIME_WINDOWS);
const REGION_IDS = new Set<string>(REGIONAL_PRESET_IDS);
const SATELLITE_IDS = new Set<string>(
  SATELLITE_IMAGERY_SOURCES.map((source) => source.id),
);
const INCIDENT_ID = /^[A-Za-z0-9][A-Za-z0-9:._~@/-]{0,199}$/;

function fixed(value: number, precision: number): string {
  return String(Number(value.toFixed(precision)));
}

function validCenter(value: string | null): [number, number] | undefined {
  const parts = value?.split(',');
  if (!parts || parts.length !== 2) return undefined;
  const latitude = Number(parts[0]);
  const longitude = Number(parts[1]);
  return Number.isFinite(latitude) &&
    Number.isFinite(longitude) &&
    latitude >= -90 &&
    latitude <= 90 &&
    longitude >= -180 &&
    longitude <= 180
    ? [latitude, longitude]
    : undefined;
}

function validZoom(value: string | null): number | undefined {
  const zoom = Number(value);
  return value !== null && Number.isFinite(zoom) && zoom >= 2 && zoom <= 18
    ? zoom
    : undefined;
}

function parseRegion(value: string | null): RegionalSelection | undefined {
  return value === 'custom' || (value !== null && REGION_IDS.has(value))
    ? (value as RegionalSelection)
    : undefined;
}

function parseLayers(
  value: string | null,
  defaults: MapLayerState,
): MapLayerState['visibility'] {
  if (value === null) return { ...defaults.visibility };
  if (value === '-') {
    return Object.fromEntries(
      MAP_LAYER_REGISTRY.map((layer) => [layer.id, false]),
    ) as MapLayerState['visibility'];
  }
  const requested = value.split(',');
  if (
    requested.length === 0 ||
    requested.some((id) => !LAYER_IDS.has(id as MapLayerId))
  ) {
    return { ...defaults.visibility };
  }
  const visible = new Set(requested);
  return Object.fromEntries(
    MAP_LAYER_REGISTRY.map((layer) => [layer.id, visible.has(layer.id)]),
  ) as MapLayerState['visibility'];
}

export function serializeMapUrlState(state: MapUrlState): string {
  const parameters = new URLSearchParams();
  parameters.set(
    'c',
    `${fixed(state.view.centerLatitude, 4)},${fixed(state.view.centerLongitude, 4)}`,
  );
  parameters.set('z', fixed(state.view.zoom, 1));
  parameters.set('r', state.regionalPreset);
  if (state.selectedIncidentId && INCIDENT_ID.test(state.selectedIncidentId)) {
    parameters.set('i', state.selectedIncidentId);
  }
  const visibleLayers = MAP_LAYER_REGISTRY.filter(
    (layer) => state.layerState.visibility[layer.id],
  ).map((layer) => layer.id);
  parameters.set('l', visibleLayers.length > 0 ? visibleLayers.join(',') : '-');
  parameters.set('t', state.layerState.timeWindow);
  parameters.set('s', state.satelliteSourceId);
  const source = SATELLITE_IMAGERY_SOURCES.find(
    (candidate) => candidate.id === state.satelliteSourceId,
  );
  if (
    source &&
    state.satelliteObservationTime &&
    validObservationTime(source, state.satelliteObservationTime)
  ) {
    parameters.set('o', state.satelliteObservationTime);
  }
  return parameters.toString();
}

export function parseMapUrlState(search: string, defaults: MapUrlState): MapUrlState {
  const parameters = new URLSearchParams(search);
  const parsedRegion = parseRegion(parameters.get('r'));
  const region = parsedRegion ?? defaults.regionalPreset;
  const regionView =
    region !== 'custom'
      ? regionalPreset(region as RegionalPresetId).view
      : defaults.view;
  const center = validCenter(parameters.get('c'));
  const zoom = validZoom(parameters.get('z'));
  const incidentId = parameters.get('i');
  const timeWindow = parameters.get('t');
  const sourceId = parameters.get('s');
  const satelliteSourceId =
    sourceId !== null && SATELLITE_IDS.has(sourceId)
      ? (sourceId as SatelliteSourceId)
      : defaults.satelliteSourceId;
  const source = SATELLITE_IMAGERY_SOURCES.find(
    (candidate) => candidate.id === satelliteSourceId,
  );
  const observationTime = parameters.get('o') ?? undefined;
  return {
    view: {
      centerLatitude: center?.[0] ?? regionView.centerLatitude,
      centerLongitude: center?.[1] ?? regionView.centerLongitude,
      zoom: zoom ?? regionView.zoom,
    },
    regionalPreset: region,
    selectedIncidentId:
      incidentId !== null && INCIDENT_ID.test(incidentId)
        ? incidentId
        : defaults.selectedIncidentId,
    layerState: {
      visibility: parseLayers(parameters.get('l'), defaults.layerState),
      timeWindow:
        timeWindow !== null && TIME_WINDOWS.has(timeWindow)
          ? (timeWindow as MapTimeWindow)
          : defaults.layerState.timeWindow,
      activePreset: undefined,
    },
    satelliteSourceId,
    satelliteObservationTime:
      source && observationTime && validObservationTime(source, observationTime)
        ? observationTime
        : sourceId === null
          ? defaults.satelliteObservationTime
          : undefined,
  };
}

export type MapUrlStateHistory = {
  start: () => void;
  schedule: (state: MapUrlState) => void;
  stop: () => void;
};

export function createMapUrlStateHistory(
  defaults: MapUrlState,
  onRestore: (state: MapUrlState) => void,
  targetWindow: Window,
  debounceMs = 350,
): MapUrlStateHistory {
  let started = false;
  let timer: ReturnType<typeof setTimeout> | undefined;
  let pending: MapUrlState | undefined;

  function clearPending() {
    if (timer !== undefined) clearTimeout(timer);
    timer = undefined;
    pending = undefined;
  }

  function restore() {
    clearPending();
    onRestore(parseMapUrlState(targetWindow.location.search, defaults));
  }

  return {
    start() {
      if (started) return;
      started = true;
      targetWindow.addEventListener('popstate', restore);
      restore();
    },
    schedule(state) {
      pending = state;
      if (timer !== undefined) clearTimeout(timer);
      timer = setTimeout(() => {
        const next = pending;
        timer = undefined;
        pending = undefined;
        if (!next || !started) return;
        const query = serializeMapUrlState(next);
        if (query === targetWindow.location.search.replace(/^\?/, '')) return;
        targetWindow.history.pushState(
          null,
          '',
          `${targetWindow.location.pathname}?${query}${targetWindow.location.hash}`,
        );
      }, debounceMs);
    },
    stop() {
      if (!started) return;
      started = false;
      clearPending();
      targetWindow.removeEventListener('popstate', restore);
    },
  };
}
