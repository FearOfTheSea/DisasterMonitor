import { afterEach, describe, expect, it, vi } from 'vitest';
import { toLonLat } from 'ol/proj';

import type {
  ActiveIncident,
  DisasterType,
  IncidentGeometry,
} from '@/features/incidents/model/activeIncidents';
import {
  activeIncidentMapFeatures,
  partitionActiveIncidentMapFeatures,
} from '@/features/map/model/activeIncidentMap';
import { OpenLayersMapAdapter } from '@/features/map/adapters/openLayersMapAdapter';
import type { WeatherAlert } from '@/features/weather/model/weatherAlert';

const SOURCE = {
  source_id: 'six-hazard-fixture',
  publisher: 'Six hazard fixture',
  title: 'Deterministic incident record',
  canonical_url: 'https://example.test/active-incidents',
  published_at: '2026-08-06T02:00:00Z',
  updated_at: '2026-08-06T02:30:00Z',
  retrieved_at: '2026-08-06T03:00:00Z',
  snapshot_id: null,
};

function incident(
  eventId: string,
  disaster: DisasterType,
  geometry: IncidentGeometry | null,
): ActiveIncident {
  return {
    event_id: eventId,
    disaster,
    location: `${disaster} fixture`,
    event_time: '2026-08-06T02:00:00Z',
    geometry,
    measurements: [],
    provider_ids: [`fixture:${eventId}`],
    provider_tier: 'primary',
    source_authority: 'scientific_authority',
    source: SOURCE,
  };
}

const SIX_HAZARD_INCIDENTS: ActiveIncident[] = [
  incident('fixture-earthquake', 'earthquake', {
    kind: 'point',
    coordinates: [{ latitude: 52, longitude: -170 }],
    description: null,
    source_id: SOURCE.source_id,
    estimated: false,
  }),
  incident('fixture-flood', 'flood', {
    kind: 'point',
    coordinates: [{ latitude: 15, longitude: 105 }],
    description: null,
    source_id: SOURCE.source_id,
    estimated: true,
  }),
  incident('fixture-wildfire', 'wildfire', {
    kind: 'area',
    coordinates: [
      { latitude: -1, longitude: -121 },
      { latitude: 1, longitude: -121 },
      { latitude: 1, longitude: -119 },
      { latitude: -1, longitude: -119 },
    ],
    description: null,
    source_id: SOURCE.source_id,
    estimated: false,
  }),
  incident('fixture-landslide', 'landslide', {
    kind: 'point',
    coordinates: [{ latitude: 23.5, longitude: 121 }],
    description: null,
    source_id: SOURCE.source_id,
    estimated: false,
  }),
  incident('fixture-cyclone', 'tropical_cyclone', {
    kind: 'track',
    coordinates: [
      { latitude: 20, longitude: 145 },
      { latitude: 20, longitude: 155 },
    ],
    description: null,
    source_id: SOURCE.source_id,
    estimated: false,
  }),
  incident('fixture-volcano', 'volcanic_eruption', {
    kind: 'point',
    coordinates: [{ latitude: -3, longitude: 36 }],
    description: null,
    source_id: SOURCE.source_id,
    estimated: false,
  }),
];

describe('activeIncidentMapFeatures', () => {
  it('preserves the identity, hazard, geometry, and estimation metadata of all six hazards', () => {
    const features = activeIncidentMapFeatures(SIX_HAZARD_INCIDENTS);

    expect(features).toEqual(
      SIX_HAZARD_INCIDENTS.map((item) => ({
        incidentId: item.event_id,
        disaster: item.disaster,
        geometry: item.geometry,
      })),
    );
    expect(features).toHaveLength(6);
    expect(
      features.find((feature) => feature.disaster === 'flood')?.geometry,
    ).toMatchObject({ kind: 'point', estimated: true });
  });

  it('excludes descriptive and invalid-cardinality geometry without fabricating coordinates', () => {
    const nonRenderable = [
      incident('descriptive', 'flood', {
        kind: 'descriptive',
        coordinates: [],
        description: 'Provider supplied location text only.',
        source_id: SOURCE.source_id,
        estimated: false,
      }),
      incident('empty-point', 'earthquake', {
        kind: 'point',
        coordinates: [],
        description: null,
        source_id: SOURCE.source_id,
        estimated: false,
      }),
      incident('short-track', 'tropical_cyclone', {
        kind: 'track',
        coordinates: [{ latitude: 20, longitude: 145 }],
        description: null,
        source_id: SOURCE.source_id,
        estimated: false,
      }),
      incident('short-area', 'wildfire', {
        kind: 'area',
        coordinates: [
          { latitude: -1, longitude: -121 },
          { latitude: 1, longitude: -119 },
        ],
        description: null,
        source_id: SOURCE.source_id,
        estimated: false,
      }),
    ];

    expect(activeIncidentMapFeatures(nonRenderable)).toEqual([]);
  });

  it('partitions only point incidents for clustering without replacing source geometry', () => {
    const features = activeIncidentMapFeatures(SIX_HAZARD_INCIDENTS);

    const partition = partitionActiveIncidentMapFeatures(features);

    expect(partition.clusteredPoints.map((item) => item.incidentId)).toEqual([
      'fixture-earthquake',
      'fixture-flood',
      'fixture-landslide',
      'fixture-volcano',
    ]);
    expect(partition.sourceGeometries.map((item) => item.incidentId)).toEqual([
      'fixture-wildfire',
      'fixture-cyclone',
    ]);
    expect(partition.sourceGeometries.map((item) => item.geometry.kind)).toEqual([
      'area',
      'track',
    ]);
  });
});

describe('OpenLayers active incident clustering', () => {
  afterEach(() => document.body.replaceChildren());

  it('clusters only point records while retaining area and track source geometry', () => {
    vi.stubGlobal(
      'ResizeObserver',
      class {
        observe() {}
        unobserve() {}
        disconnect() {}
      },
    );
    const target = document.createElement('div');
    target.style.width = '800px';
    target.style.height = '600px';
    document.body.append(target);
    const adapter = new OpenLayersMapAdapter({
      target,
      initialView: { centerLatitude: 0, centerLongitude: 0, zoom: 2 },
      onViewChange: vi.fn(),
      onSelectIncident: vi.fn(),
    });

    adapter.setActiveIncidents(activeIncidentMapFeatures(SIX_HAZARD_INCIDENTS));
    adapter.setSelectedIncident('fixture-flood');
    adapter.setLayerVisibility({
      'active-incidents': false,
      'satellite-imagery': false,
      'cop-evidence': true,
      'cyclone-supplemental': true,
      'authoritative-weather-alerts': true,
      'compound-correlations': true,
    });

    type LayerView = {
      get: (key: string) => unknown;
      getVisible: () => boolean;
      getSource: () => {
        getFeatures: () => Array<{ get: (key: string) => unknown }>;
        getSource?: () => {
          getFeatures: () => Array<{ get: (key: string) => unknown }>;
        };
      };
    };
    type AdapterView = {
      map: { getLayers: () => { getArray: () => LayerView[] } };
    };
    const layers = (adapter as unknown as AdapterView).map.getLayers().getArray();
    const clusteredPoints = layers.find(
      (layer) => layer.get('dmIncidentRepresentation') === 'clustered-points',
    );
    const sourceGeometry = layers.find(
      (layer) => layer.get('dmIncidentRepresentation') === 'source-geometry',
    );
    const pointFeatures =
      clusteredPoints?.getSource().getSource?.().getFeatures() ?? [];
    const geometryFeatures = sourceGeometry?.getSource().getFeatures() ?? [];

    expect(
      pointFeatures.map((feature) => feature.get('incidentId')).toSorted(),
    ).toEqual([
      'fixture-earthquake',
      'fixture-flood',
      'fixture-landslide',
      'fixture-volcano',
    ]);
    expect(
      pointFeatures
        .find((feature) => feature.get('incidentId') === 'fixture-flood')
        ?.get('selected'),
    ).toBe(true);
    expect(geometryFeatures.map((feature) => feature.get('incidentId'))).toEqual([
      'fixture-wildfire',
      'fixture-cyclone',
    ]);
    expect(clusteredPoints?.getVisible()).toBe(false);
    expect(sourceGeometry?.getVisible()).toBe(false);

    adapter.destroy();
    vi.unstubAllGlobals();
  });

  it('draws only exact source-supplied weather polygons on a distinct layer', () => {
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
    const base: Omit<WeatherAlert, 'provider_alert_id' | 'geometry'> = {
      source_id: 'nws-weather-alerts',
      publisher: 'NOAA/National Weather Service',
      event: 'Tornado Warning',
      headline: null,
      severity: 'extreme',
      urgency: 'immediate',
      certainty: 'observed',
      sent: null,
      effective: null,
      onset: null,
      expires: null,
      affected_area: 'Fixture County',
      canonical_url: null,
      retrieved_at: '2026-09-01T02:00:00Z',
      attribution: 'NOAA/National Weather Service',
      limitations: [],
    };
    const ring = [
      { latitude: 35, longitude: -98 },
      { latitude: 36, longitude: -98 },
      { latitude: 36, longitude: -97 },
      { latitude: 35, longitude: -98 },
    ];

    adapter.setWeatherAlerts([
      {
        ...base,
        provider_alert_id: 'with-geometry',
        geometry: { kind: 'polygon', rings: [ring] },
      },
      { ...base, provider_alert_id: 'without-geometry', geometry: null },
    ]);

    type LayerView = {
      get: (key: string) => unknown;
      getSource: () => {
        getFeatures: () => Array<{
          get: (key: string) => unknown;
          getGeometry: () => { getCoordinates: () => number[][][] } | undefined;
        }>;
      };
    };
    type AdapterView = {
      map: { getLayers: () => { getArray: () => LayerView[] } };
    };
    const layer = (adapter as unknown as AdapterView).map
      .getLayers()
      .getArray()
      .find(
        (candidate) => candidate.get('dmLayerId') === 'authoritative-weather-alerts',
      );
    const features = layer?.getSource().getFeatures() ?? [];
    const coordinates = features[0]
      ?.getGeometry()
      ?.getCoordinates()[0]
      .map((point) => toLonLat(point));

    expect(features).toHaveLength(1);
    expect(features[0]?.get('alertId')).toBe('with-geometry');
    expect(coordinates).toEqual(
      ring.map((point) =>
        expect.arrayContaining([
          expect.closeTo(point.longitude, 8),
          expect.closeTo(point.latitude, 8),
        ]),
      ),
    );

    adapter.destroy();
    vi.unstubAllGlobals();
  });
});
