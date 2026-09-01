import type {
  ActiveIncident,
  CompoundHazardCorrelation,
} from '@/features/incidents/model/activeIncidents';
import {
  MAP_LAYER_REGISTRY,
  type MapLayerId,
} from '@/features/map/model/mapLayerRegistry';

export const MAP_TIME_WINDOWS = ['1h', '6h', '24h', '48h', '7d'] as const;
export type MapTimeWindow = (typeof MAP_TIME_WINDOWS)[number];

export const MAP_LAYER_PRESETS = [
  'minimal',
  'incidents',
  'evidence',
  'forecasts',
  'warnings',
  'satellite',
  'all',
] as const;
export type MapLayerPreset = (typeof MAP_LAYER_PRESETS)[number];

export type MapLayerVisibility = Record<MapLayerId, boolean>;

export type MapLayerState = {
  visibility: MapLayerVisibility;
  timeWindow: MapTimeWindow;
  activePreset?: MapLayerPreset;
};

const PRESET_LAYERS: Record<MapLayerPreset, readonly MapLayerId[]> = {
  minimal: ['active-incidents'],
  incidents: ['active-incidents', 'compound-correlations'],
  evidence: ['active-incidents', 'cop-evidence'],
  forecasts: ['active-incidents', 'cyclone-supplemental'],
  warnings: ['active-incidents', 'authoritative-weather-alerts'],
  satellite: ['active-incidents', 'satellite-imagery'],
  all: MAP_LAYER_REGISTRY.map((layer) => layer.id),
};

const WINDOW_MILLISECONDS: Record<MapTimeWindow, number> = {
  '1h': 60 * 60 * 1_000,
  '6h': 6 * 60 * 60 * 1_000,
  '24h': 24 * 60 * 60 * 1_000,
  '48h': 48 * 60 * 60 * 1_000,
  '7d': 7 * 24 * 60 * 60 * 1_000,
};

export function createDefaultMapLayerState(): MapLayerState {
  return {
    visibility: Object.fromEntries(
      MAP_LAYER_REGISTRY.map((layer) => [layer.id, layer.defaultVisible]),
    ) as MapLayerVisibility,
    timeWindow: '7d',
  };
}

export function applyMapLayerPreset(
  state: MapLayerState,
  preset: MapLayerPreset,
): MapLayerState {
  const visibleLayers = new Set(PRESET_LAYERS[preset]);
  return {
    ...state,
    activePreset: preset,
    visibility: Object.fromEntries(
      MAP_LAYER_REGISTRY.map((layer) => [layer.id, visibleLayers.has(layer.id)]),
    ) as MapLayerVisibility,
  };
}

export function setMapLayerVisibility(
  state: MapLayerState,
  layerId: MapLayerId,
  visible: boolean,
): MapLayerState {
  return {
    ...state,
    activePreset: undefined,
    visibility: { ...state.visibility, [layerId]: visible },
  };
}

export function setMapTimeWindow(
  state: MapLayerState,
  timeWindow: MapTimeWindow,
): MapLayerState {
  return { ...state, timeWindow };
}

export function filterIncidentsForDisplay(
  incidents: readonly ActiveIncident[],
  snapshotRetrievedAt: string,
  timeWindow: MapTimeWindow,
): ActiveIncident[] {
  const retrievedAt = Date.parse(snapshotRetrievedAt);
  if (!Number.isFinite(retrievedAt)) return [];
  const cutoff = retrievedAt - WINDOW_MILLISECONDS[timeWindow];
  return incidents.filter((incident) => {
    const eventTime = Date.parse(incident.event_time);
    return (
      Number.isFinite(eventTime) && eventTime >= cutoff && eventTime <= retrievedAt
    );
  });
}

export function filterCorrelationsForDisplay(
  correlations: readonly CompoundHazardCorrelation[],
  incidents: readonly ActiveIncident[],
  snapshotRetrievedAt: string,
  timeWindow: MapTimeWindow,
): CompoundHazardCorrelation[] {
  const displayedIds = new Set(
    filterIncidentsForDisplay(incidents, snapshotRetrievedAt, timeWindow).map(
      (incident) => incident.event_id,
    ),
  );
  return correlations.filter(
    (correlation) =>
      displayedIds.has(correlation.first_event_id) &&
      displayedIds.has(correlation.second_event_id),
  );
}
