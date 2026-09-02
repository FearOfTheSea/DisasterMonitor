import type {
  CreateIncidentWatchOperatorActionResponse,
  OpenPanelOperatorActionResponse,
  SetTimeWindowOperatorActionResponse,
  ShowLayerOperatorActionResponse,
} from '@/shared/api/generated/assistant';
import {
  MAP_LAYER_REGISTRY,
  type MapLayerId,
} from '@/features/map/model/mapLayerRegistry';
import {
  MAP_TIME_WINDOWS,
  setMapLayerVisibility,
  setMapTimeWindow,
  type MapLayerState,
  type MapTimeWindow,
} from '@/features/map/model/mapLayerState';

export type OperatorAction =
  | OpenPanelOperatorActionResponse
  | SetTimeWindowOperatorActionResponse
  | ShowLayerOperatorActionResponse
  | CreateIncidentWatchOperatorActionResponse;
export type OperatorPanelId = 'findings' | 'sources' | 'watches' | 'operations';

export type AutomaticOperatorActionResult = {
  mapLayerState: MapLayerState;
  openPanels: OperatorPanelId[];
};

const PANEL_ACTIONS = {
  'open:findings': 'findings',
  'open:sources': 'sources',
  'open:watches': 'watches',
  'open:operations': 'operations',
} as const satisfies Record<string, OperatorPanelId>;

const TIME_ACTIONS = new Set(
  MAP_TIME_WINDOWS.map((timeWindow) => `time:${timeWindow}`),
);
const LAYER_IDS = new Set(MAP_LAYER_REGISTRY.map((layer) => layer.id));
const WATCH_INTERVALS = new Set([900, 1800, 3600, 21600, 86400]);

export function executeAutomaticOperatorActions(
  actions: readonly OperatorAction[],
  mapLayerState: MapLayerState,
): AutomaticOperatorActionResult {
  if (!operatorActionsAreConsistent(actions)) {
    return { mapLayerState, openPanels: [] };
  }

  let nextMapLayerState = mapLayerState;
  const openPanels: OperatorPanelId[] = [];
  for (const action of actions) {
    if (action.risk !== 'automatic') continue;
    if (action.action_type === 'open_panel') {
      openPanels.push(action.value);
    } else if (action.action_type === 'set_time_window') {
      nextMapLayerState = setMapTimeWindow(
        nextMapLayerState,
        action.value as MapTimeWindow,
      );
    } else if (action.action_type === 'show_layer') {
      nextMapLayerState = setMapLayerVisibility(
        nextMapLayerState,
        action.value as MapLayerId,
        true,
      );
    }
  }
  return { mapLayerState: nextMapLayerState, openPanels };
}

export function operatorActionsAreConsistent(
  actions: readonly OperatorAction[],
): boolean {
  if (actions.length > 4) return false;
  const actionIds = new Set<string>();
  for (const action of actions) {
    if (actionIds.has(action.action_id)) return false;
    actionIds.add(action.action_id);
    if (action.action_type === 'open_panel') {
      if (
        action.risk !== 'automatic' ||
        action.operation !== 'open' ||
        action.target !== 'panel' ||
        PANEL_ACTIONS[action.action_id as keyof typeof PANEL_ACTIONS] !== action.value
      ) {
        return false;
      }
    } else if (action.action_type === 'set_time_window') {
      if (
        action.risk !== 'automatic' ||
        action.operation !== 'set' ||
        action.target !== 'time_window' ||
        !TIME_ACTIONS.has(action.action_id) ||
        action.action_id !== `time:${action.value}`
      ) {
        return false;
      }
    } else if (action.action_type === 'show_layer') {
      const layerId = action.action_id.replace('show-layer:', '');
      if (
        action.risk !== 'automatic' ||
        action.operation !== 'show' ||
        action.target !== 'map_layer' ||
        !LAYER_IDS.has(layerId as MapLayerId) ||
        action.action_id !== `show-layer:${action.value}`
      ) {
        return false;
      }
    } else if (
      action.action_type !== 'create_incident_watch' ||
      action.risk !== 'confirmation_required' ||
      !WATCH_INTERVALS.has(action.refresh_interval_seconds) ||
      action.action_id !== `create-watch:${action.refresh_interval_seconds}` ||
      (action.scope.kind === 'country' &&
        (!action.scope.country_code || !action.scope.country_name)) ||
      (action.scope.kind === 'worldwide' &&
        (action.scope.country_code !== null || action.scope.country_name !== null))
    ) {
      return false;
    }
  }
  return true;
}
