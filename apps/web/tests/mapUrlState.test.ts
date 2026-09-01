import { afterEach, describe, expect, it, vi } from 'vitest';

import {
  createMapUrlStateHistory,
  parseMapUrlState,
  serializeMapUrlState,
  type MapUrlState,
} from '@/features/map/model/mapUrlState';
import { createDefaultMapLayerState } from '@/features/map/model/mapLayerState';
import { DEFAULT_MAP_VIEW } from '@/features/map/model/mapView';

const DEFAULTS: MapUrlState = {
  view: DEFAULT_MAP_VIEW,
  regionalPreset: 'custom',
  selectedIncidentId: undefined,
  layerState: createDefaultMapLayerState(),
  satelliteSourceId: 'nasa-viirs-snpp-true-color',
  satelliteObservationTime: undefined,
};

describe('bounded map URL state', () => {
  afterEach(() => {
    vi.useRealTimers();
    window.history.replaceState(null, '', '/');
  });

  it('round-trips every supported presentation field with stable parameters', () => {
    const state: MapUrlState = {
      view: { centerLatitude: 48.8566, centerLongitude: 2.3522, zoom: 5.5 },
      regionalPreset: 'europe',
      selectedIncidentId: 'usgs:event-1',
      layerState: {
        ...createDefaultMapLayerState(),
        timeWindow: '24h',
        visibility: {
          ...createDefaultMapLayerState().visibility,
          'satellite-imagery': true,
          'authoritative-weather-alerts': true,
        },
      },
      satelliteSourceId: 'nasa-modis-terra-true-color',
      satelliteObservationTime: '2026-09-01',
    };

    const serialized = serializeMapUrlState(state);
    const parsed = parseMapUrlState(serialized, DEFAULTS);

    expect([...new URLSearchParams(serialized).keys()]).toEqual([
      'c',
      'z',
      'r',
      'i',
      'l',
      't',
      's',
      'o',
    ]);
    expect(parsed).toEqual(state);
  });

  it('fails unknown or malformed fields independently to defaults', () => {
    const parsed = parseMapUrlState(
      '?c=999,NaN&z=-3&r=antarctica&i=%00bad&l=made-up&t=all&s=secret&o=payload',
      DEFAULTS,
    );

    expect(parsed).toEqual(DEFAULTS);
    expect(parseMapUrlState('', DEFAULTS)).toEqual(DEFAULTS);
  });

  it('debounces history updates and restores parsed state on popstate', async () => {
    vi.useFakeTimers();
    const restored = vi.fn();
    const history = createMapUrlStateHistory(DEFAULTS, restored, window, 250);
    history.start();
    expect(restored).toHaveBeenLastCalledWith(DEFAULTS);

    const europe = {
      ...DEFAULTS,
      view: { centerLatitude: 54, centerLongitude: 15, zoom: 4 },
      regionalPreset: 'europe' as const,
    };
    history.schedule(europe);
    history.schedule({ ...europe, view: { ...europe.view, zoom: 4.5 } });
    await vi.advanceTimersByTimeAsync(249);
    expect(window.location.search).toBe('');
    await vi.advanceTimersByTimeAsync(1);
    expect(window.location.search).toContain('r=europe');

    window.history.replaceState(null, '', '/?r=global');
    window.dispatchEvent(new PopStateEvent('popstate'));
    expect(restored).toHaveBeenLastCalledWith(
      expect.objectContaining({ regionalPreset: 'global' }),
    );
    history.stop();
  });
});
