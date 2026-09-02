import { describe, expect, it } from 'vitest';

import {
  executeAutomaticOperatorActions,
  operatorActionsAreConsistent,
} from '@/features/assistant/model/operatorActions';
import { createDefaultMapLayerState } from '@/features/map/model/mapLayerState';
import type { OperatorAction } from '@/shared/types/assistant';

const openWatches: OperatorAction = {
  action_id: 'open:watches',
  action_type: 'open_panel',
  risk: 'automatic',
  operation: 'open',
  target: 'panel',
  value: 'watches',
  label: 'Open Incident Watches',
};
const openFindings: OperatorAction = {
  action_id: 'open:findings',
  action_type: 'open_panel',
  risk: 'automatic',
  operation: 'open',
  target: 'panel',
  value: 'findings',
  label: 'Open Findings',
};

const setTime: OperatorAction = {
  action_id: 'time:24h',
  action_type: 'set_time_window',
  risk: 'automatic',
  operation: 'set',
  target: 'time_window',
  value: '24h',
  label: 'Show a 24-hour display window',
};

const showSatellite: OperatorAction = {
  action_id: 'show-layer:satellite-imagery',
  action_type: 'show_layer',
  risk: 'automatic',
  operation: 'show',
  target: 'map_layer',
  value: 'satellite-imagery',
  label: 'Show Satellite imagery',
};

const watchProposal: OperatorAction = {
  action_id: 'create-watch:900',
  action_type: 'create_incident_watch',
  risk: 'confirmation_required',
  disaster: 'earthquake',
  scope: { kind: 'country', country_code: 'JPN', country_name: 'Japan' },
  refresh_interval_seconds: 900,
  label: 'Create a 15-minute earthquake watch for Japan',
};

describe('operator action executor', () => {
  it('applies bounded automatic actions and leaves confirmation for the UI', () => {
    const initial = createDefaultMapLayerState();
    const result = executeAutomaticOperatorActions(
      [openFindings, setTime, showSatellite, watchProposal],
      initial,
    );

    expect(result.openPanels).toEqual(['findings']);
    expect(result.mapLayerState.timeWindow).toBe('24h');
    expect(result.mapLayerState.visibility['satellite-imagery']).toBe(true);
    expect(executeAutomaticOperatorActions([openWatches], initial).openPanels).toEqual([
      'watches',
    ]);
  });

  it('makes layer visibility idempotently true rather than toggling it', () => {
    const initial = {
      ...createDefaultMapLayerState(),
      visibility: {
        ...createDefaultMapLayerState().visibility,
        'satellite-imagery': true,
      },
    };

    const result = executeAutomaticOperatorActions([showSatellite], initial);

    expect(result.mapLayerState.visibility['satellite-imagery']).toBe(true);
  });

  it('fails closed when the action list is duplicated or oversized', () => {
    const initial = createDefaultMapLayerState();
    expect(operatorActionsAreConsistent([openWatches, openWatches])).toBe(false);
    expect(
      executeAutomaticOperatorActions(
        [openWatches, openWatches, setTime, showSatellite, watchProposal],
        initial,
      ),
    ).toEqual({ mapLayerState: initial, openPanels: [] });
  });

  it('fails closed for malformed confirmation actions', () => {
    const malformed = {
      ...watchProposal,
      action_type: 'unknown_action',
      refresh_interval_seconds: 123,
      action_id: 'create-watch:123',
    } as unknown as OperatorAction;

    expect(operatorActionsAreConsistent([malformed])).toBe(false);
    expect(
      executeAutomaticOperatorActions([malformed], createDefaultMapLayerState()),
    ).toEqual({
      mapLayerState: createDefaultMapLayerState(),
      openPanels: [],
    });
  });
});
