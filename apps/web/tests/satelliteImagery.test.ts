import { afterEach, describe, expect, it, vi } from 'vitest';

import { OpenLayersMapAdapter } from '@/features/map/adapters/openLayersMapAdapter';
import {
  SATELLITE_IMAGERY_SOURCES,
  buildNasaGibsTileUrl,
  observationTimeForSource,
  sourceById,
} from '@/features/map/model/satelliteImagery';
import { buildProtectedSatelliteTileUrl } from '@/features/map/api/satelliteImageryClient';
import { commonOperationalPicture } from './fixtures/multimodal';

afterEach(() => {
  vi.unstubAllGlobals();
  document.body.replaceChildren();
});

describe('satellite imagery source model', () => {
  it('defines the exact source catalog and source-appropriate capabilities', () => {
    expect(SATELLITE_IMAGERY_SOURCES.map((source) => source.id)).toEqual([
      'nasa-viirs-snpp-true-color',
      'nasa-modis-terra-true-color',
      'nasa-modis-aqua-true-color',
      'nasa-goes-east-geocolor',
      'nasa-goes-west-geocolor',
      'nasa-himawari-9-visible',
      'copernicus-sentinel-2-true-color',
      'planet-configured-mosaic',
    ]);
    expect(SATELLITE_IMAGERY_SOURCES.slice(0, 3)).toMatchObject([
      { temporalMode: 'daily', maximumUsefulZoom: 9, available: true },
      { temporalMode: 'daily', maximumUsefulZoom: 9, available: true },
      { temporalMode: 'daily', maximumUsefulZoom: 9, available: true },
    ]);
    expect(SATELLITE_IMAGERY_SOURCES.slice(3, 6)).toMatchObject([
      { temporalMode: 'subdaily', temporalStepMinutes: 10, maximumUsefulZoom: 7 },
      { temporalMode: 'subdaily', temporalStepMinutes: 10, maximumUsefulZoom: 7 },
      { temporalMode: 'subdaily', temporalStepMinutes: 10, maximumUsefulZoom: 7 },
    ]);
    expect(sourceById('copernicus-sentinel-2-true-color')).toMatchObject({
      temporalMode: 'daily',
      available: false,
      access: { kind: 'disaster-monitor-api' },
    });
    expect(sourceById('planet-configured-mosaic')).toMatchObject({
      temporalMode: 'fixed',
      available: false,
      access: { kind: 'disaster-monitor-api' },
    });
  });

  it('constructs exact daily NASA GIBS Web Mercator tile URLs without network access', () => {
    expect(buildNasaGibsTileUrl('nasa-viirs-snpp-true-color', '2026-08-22')).toBe(
      'https://gibs.earthdata.nasa.gov/wmts/epsg3857/best/' +
        'VIIRS_SNPP_CorrectedReflectance_TrueColor/default/2026-08-22/' +
        'GoogleMapsCompatible_Level9/{z}/{y}/{x}.jpeg',
    );
    expect(buildNasaGibsTileUrl('nasa-modis-terra-true-color', '2026-08-22')).toContain(
      'MODIS_Terra_CorrectedReflectance_TrueColor/default/2026-08-22/' +
        'GoogleMapsCompatible_Level9',
    );
    expect(buildNasaGibsTileUrl('nasa-modis-aqua-true-color', '2026-08-22')).toContain(
      'MODIS_Aqua_CorrectedReflectance_TrueColor/default/2026-08-22/' +
        'GoogleMapsCompatible_Level9',
    );
  });

  it('constructs 10-minute UTC geostationary GIBS URLs and rejects invalid times', () => {
    expect(
      buildNasaGibsTileUrl('nasa-goes-east-geocolor', '2026-08-22T12:20:00Z'),
    ).toBe(
      'https://gibs.earthdata.nasa.gov/wmts/epsg3857/best/' +
        'GOES-East_ABI_GeoColor/default/2026-08-22T12:20:00Z/' +
        'GoogleMapsCompatible_Level7/{z}/{y}/{x}.png',
    );
    expect(() => buildNasaGibsTileUrl('nasa-goes-west-geocolor', '2026-08-22')).toThrow(
      /UTC date\/time/,
    );
    expect(() =>
      buildNasaGibsTileUrl('nasa-himawari-9-visible', '2026-08-22T12:23:00Z'),
    ).toThrow(/10-minute/);
    expect(() =>
      buildNasaGibsTileUrl('nasa-viirs-snpp-true-color', '2026-02-30'),
    ).toThrow(/daily date/);
  });

  it('derives daily and UTC subdaily observation inputs without calling them live', () => {
    const now = new Date('2026-08-22T12:27:49Z');
    expect(
      observationTimeForSource(sourceById('nasa-modis-terra-true-color'), now),
    ).toBe('2026-08-22');
    expect(observationTimeForSource(sourceById('nasa-goes-west-geocolor'), now)).toBe(
      '2026-08-22T12:20:00Z',
    );
    expect(observationTimeForSource(sourceById('planet-configured-mosaic'), now)).toBe(
      undefined,
    );
    expect(
      SATELLITE_IMAGERY_SOURCES.map((source) => source.displayName).join(' '),
    ).not.toMatch(/\blive\b/i);
  });

  it('returns only DisasterMonitor URLs for protected providers', () => {
    const sentinel = buildProtectedSatelliteTileUrl(
      sourceById('copernicus-sentinel-2-true-color'),
      '2026-08-22',
      'http://localhost:8001/api/v1',
    );
    const planet = buildProtectedSatelliteTileUrl(
      sourceById('planet-configured-mosaic'),
      undefined,
      'http://localhost:8001/api/v1',
    );

    expect(sentinel).toBe(
      'http://localhost:8001/api/v1/satellite-imagery/tiles/' +
        'copernicus-sentinel-hub/copernicus-sentinel-2-true-color/' +
        '{z}/{x}/{y}?time=2026-08-22',
    );
    expect(planet).toBe(
      'http://localhost:8001/api/v1/satellite-imagery/tiles/planet/' +
        'planet-configured-mosaic/{z}/{x}/{y}',
    );
    expect(`${sentinel} ${planet}`).not.toMatch(
      /api[_-]?key|instance|sentinel-hub\.com|tiles\.planet\.com/i,
    );
  });

  it('keeps exactly one satellite raster below incident and COP vectors', () => {
    vi.stubGlobal(
      'ResizeObserver',
      class {
        observe() {}
        unobserve() {}
        disconnect() {}
      },
    );
    const target = document.createElement('div');
    document.body.append(target);
    const adapter = new OpenLayersMapAdapter({
      target,
      initialView: { centerLatitude: 0, centerLongitude: 0, zoom: 2 },
      onViewChange: vi.fn(),
      onSelectIncident: vi.fn(),
    });
    const configuration = {
      sourceId: 'nasa-viirs-snpp-true-color',
      url: buildNasaGibsTileUrl('nasa-viirs-snpp-true-color', '2026-08-22'),
      attribution: 'NASA GIBS',
      maximumUsefulZoom: 9,
      opacity: 0.75,
    };

    adapter.setSatelliteImagery(configuration);
    adapter.setSatelliteImagery({
      ...configuration,
      sourceId: 'nasa-modis-terra-true-color',
      url: buildNasaGibsTileUrl('nasa-modis-terra-true-color', '2026-08-22'),
    });
    adapter.setCommonOperationalPicture(commonOperationalPicture);
    adapter.setSatelliteOpacity(0.4);

    type LayerView = {
      get: (key: string) => unknown;
      getOpacity: () => number;
      getZIndex: () => number | undefined;
    };
    type AdapterView = {
      map: { getLayers: () => { getArray: () => LayerView[] } };
    };
    const layers = (adapter as unknown as AdapterView).map.getLayers().getArray();
    const satellites = layers.filter(
      (layer) => layer.get('dmLayerType') === 'satellite-imagery',
    );
    const satellite = satellites[0];
    const incident = layers.find(
      (layer) => layer.get('dmLayerType') === 'active-incidents',
    );
    const cop = layers.find(
      (layer) => layer.get('dmLayerType') === 'common-operational-picture',
    );

    expect(satellites).toHaveLength(1);
    expect(satellite.get('dmSatelliteSourceId')).toBe('nasa-modis-terra-true-color');
    expect(satellite.getOpacity()).toBe(0.4);
    expect(satellite.getZIndex()).toBeLessThan(incident?.getZIndex() ?? 0);
    expect(satellite.getZIndex()).toBeLessThan(cop?.getZIndex() ?? 0);

    adapter.destroy();
  });
});
