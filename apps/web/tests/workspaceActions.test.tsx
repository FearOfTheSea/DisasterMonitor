import { act, renderHook } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { useWorkspaceActions } from '@/app/workspace/useWorkspaceActions';
import { createDefaultMapLayerState } from '@/features/map/model/mapLayerState';
import type { AssistantResponse } from '@/shared/types/assistant';

describe('workspace actions', () => {
  it('selects an incident and opens its Ground pane with a restorable URL identity', () => {
    const selectActiveIncident = vi.fn();
    const openPane = vi.fn();
    const { result } = renderHook(() =>
      useWorkspaceActions({
        ...inputs(),
        selectActiveIncident,
        openPane,
      }),
    );

    act(() => result.current.selectIncident('event-1'));

    expect(selectActiveIncident).toHaveBeenCalledWith('event-1');
    expect(openPane).toHaveBeenCalledWith('ground', 'event-1');
  });

  it('applies assistant actions to layers and opens the requested workspace', async () => {
    const setMapLayerState = vi.fn();
    const openSection = vi.fn();
    const response = {
      operator_actions: [
        {
          action_id: 'show-layer:satellite-imagery',
          action_type: 'show_layer',
          risk: 'automatic',
          operation: 'show',
          target: 'map_layer',
          value: 'satellite-imagery',
          label: 'Show Satellite imagery',
        },
        {
          action_id: 'open:findings',
          action_type: 'open_panel',
          risk: 'automatic',
          operation: 'open',
          target: 'panel',
          value: 'findings',
          label: 'Open Findings',
        },
      ],
    } as AssistantResponse;
    const submit = vi.fn().mockResolvedValue(response);
    const { result } = renderHook(() =>
      useWorkspaceActions({
        ...inputs(),
        submit,
        setMapLayerState,
        openSection,
      }),
    );

    let submitted = false;
    await act(async () => {
      submitted = await result.current.submitQuestion('Show satellite and findings');
    });

    expect(submitted).toBe(true);
    expect(setMapLayerState.mock.calls[0][0].visibility['satellite-imagery']).toBe(
      true,
    );
    expect(openSection).toHaveBeenCalledWith('activity');
  });
});

function inputs() {
  return {
    submit: vi.fn().mockResolvedValue(undefined),
    mapView: { centerLatitude: 0, centerLongitude: 0, zoom: 2 },
    mapLayerState: createDefaultMapLayerState(),
    setMapLayerState: vi.fn(),
    incidents: [],
    selectedIncidentId: undefined,
    selectedIncident: undefined,
    selectActiveIncident: vi.fn(),
    selectWatchIncident: vi.fn(),
    clearSelectedIncident: vi.fn(),
    setFocusRequestToken: vi.fn(),
    selectRegion: vi.fn(),
    navigate: vi.fn(),
    openPane: vi.fn(),
    openSection: vi.fn(),
  };
}
