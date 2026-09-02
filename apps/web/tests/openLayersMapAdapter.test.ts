import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { fromLonLat } from 'ol/proj';

import {
  OpenLayersMapAdapter,
  type SatelliteLayerConfiguration,
} from '@/features/map/adapters/openLayersMapAdapter';
import type { MapView } from '@/shared/types/assistant';

type AdapterInternals = {
  map: {
    dispatchEvent: (event: string) => boolean;
    getView: () => {
      setCenter: (center: number[]) => void;
      setResolution: (resolution: number) => void;
      setZoom: (zoom: number) => void;
      beginInteraction: () => void;
      endInteraction: (duration?: number) => void;
      getResolutionForZoom: (zoom: number) => number;
    };
    getLayers: () => {
      getArray: () => Array<{
        get: (key: string) => unknown;
        getPreload: () => number;
        getSource: () => unknown;
      }>;
    };
  };
  clusteredIncidentSource: {
    getDistance: () => number;
    setDistance: (distance: number) => void;
  };
};

const adapters: OpenLayersMapAdapter[] = [];

function createAdapter(
  initialView: MapView = { centerLatitude: 0, centerLongitude: 0, zoom: 8 },
  onViewChange: (view: MapView) => void = vi.fn(),
): OpenLayersMapAdapter {
  const target = document.createElement('div');
  target.style.width = '800px';
  target.style.height = '600px';
  document.body.append(target);
  const adapter = new OpenLayersMapAdapter({
    target,
    initialView,
    onViewChange,
    onSelectIncident: vi.fn(),
  });
  adapters.push(adapter);
  return adapter;
}

function internals(adapter: OpenLayersMapAdapter): AdapterInternals {
  return adapter as unknown as AdapterInternals;
}

beforeEach(() => {
  vi.stubGlobal(
    'ResizeObserver',
    class {
      observe() {}
      unobserve() {}
      disconnect() {}
    },
  );
});

afterEach(() => {
  for (const adapter of adapters.splice(0)) adapter.destroy();
  vi.unstubAllGlobals();
  document.body.replaceChildren();
});

describe('OpenLayers map interaction performance', () => {
  it('does not publish center or resolution changes until moveend', () => {
    const onViewChange = vi.fn();
    const adapter = createAdapter(undefined, onViewChange);
    const { map } = internals(adapter);
    const view = map.getView();

    view.beginInteraction();
    view.setCenter(fromLonLat([137.01, 37.02]));
    view.setZoom(7);

    expect(onViewChange).not.toHaveBeenCalled();

    view.endInteraction(0);
    map.dispatchEvent('moveend');

    expect(onViewChange).toHaveBeenCalledTimes(1);
    expect(onViewChange.mock.calls[0][0]).toMatchObject({
      centerLatitude: expect.closeTo(37.02, 0.000001),
      centerLongitude: expect.closeTo(137.01, 0.000001),
      zoom: 7,
    });
  });

  it('does not report a second view change when moveend follows setView', () => {
    const onViewChange = vi.fn();
    const adapter = createAdapter(undefined, onViewChange);
    const { map } = internals(adapter);

    adapter.setView({ centerLatitude: 37.02, centerLongitude: 137.01, zoom: 7 });
    expect(onViewChange).toHaveBeenCalledTimes(1);

    map.dispatchEvent('moveend');

    expect(onViewChange).toHaveBeenCalledTimes(1);
  });

  it('keeps cluster distance stable inside one effective zoom bucket', () => {
    const adapter = createAdapter();
    const { map, clusteredIncidentSource } = internals(adapter);
    const setDistance = vi.spyOn(clusteredIncidentSource, 'setDistance');
    const view = map.getView();

    view.beginInteraction();
    view.setResolution(view.getResolutionForZoom(8.25));
    view.setResolution(view.getResolutionForZoom(8.75));

    expect(setDistance).not.toHaveBeenCalled();
    expect(clusteredIncidentSource.getDistance()).toBe(44);
  });

  it('updates cluster distance when the effective zoom bucket changes', () => {
    const adapter = createAdapter();
    const { map, clusteredIncidentSource } = internals(adapter);
    const setDistance = vi.spyOn(clusteredIncidentSource, 'setDistance');
    const view = map.getView();

    view.beginInteraction();
    view.setResolution(view.getResolutionForZoom(8.75));
    view.setResolution(view.getResolutionForZoom(9.25));
    view.setResolution(view.getResolutionForZoom(9.75));

    expect(setDistance).toHaveBeenCalledTimes(1);
    expect(setDistance).toHaveBeenCalledWith(0);
    expect(clusteredIncidentSource.getDistance()).toBe(0);
  });

  it('configures satellite tiles without fade transitions and with one-level preload', () => {
    const adapter = createAdapter();
    const configuration: SatelliteLayerConfiguration = {
      sourceId: 'nasa-viirs-snpp-true-color',
      url: 'https://example.test/{z}/{x}/{y}.jpeg',
      attribution: 'Fixture imagery',
      maximumUsefulZoom: 9,
      opacity: 0.75,
    };

    adapter.setSatelliteImagery(configuration);

    const satellite = internals(adapter)
      .map.getLayers()
      .getArray()
      .find((layer) => layer.get('dmLayerType') === 'satellite-imagery');
    const source = satellite?.getSource() as { tileOptions?: { transition?: number } };

    expect(satellite?.getPreload()).toBe(1);
    expect(source.tileOptions?.transition).toBe(0);
  });
});
