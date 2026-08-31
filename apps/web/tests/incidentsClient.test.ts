import { afterEach, describe, expect, it, vi } from 'vitest';

import { fetchActiveIncidents } from '@/features/incidents/api/incidentsClient';
import type {
  ActiveIncident,
  ActiveIncidentsSnapshot,
  DisasterType,
  IncidentGeometry,
} from '@/features/incidents/model/activeIncidents';

const DISASTERS: DisasterType[] = [
  'earthquake',
  'flood',
  'wildfire',
  'landslide',
  'tropical_cyclone',
  'volcanic_eruption',
];

function incident(disaster: DisasterType, geometry: IncidentGeometry): ActiveIncident {
  return {
    event_id: `fixture-${disaster}`,
    disaster,
    location: `${disaster} fixture`,
    event_time: '2026-08-06T02:00:00Z',
    geometry,
    measurements: [],
    provider_ids: [`fixture:${disaster}`],
    provider_tier: 'primary',
    source_authority: 'scientific_authority',
    source: {
      source_id: 'six-hazard-fixture',
      publisher: 'Six hazard fixture',
      title: `${disaster} source record`,
      canonical_url: `https://example.test/${disaster}`,
      published_at: '2026-08-06T02:00:00Z',
      updated_at: '2026-08-06T02:30:00Z',
      retrieved_at: '2026-08-06T03:00:00Z',
      snapshot_id: null,
    },
  };
}

describe('incidentsClient', () => {
  afterEach(() => vi.unstubAllGlobals());

  it('constructs a bounded Active Incidents request', async () => {
    const responseBody = {
      retrieved_at: '2026-08-20T06:00:00Z',
      incidents: [],
      coverage: [],
      warnings: [],
      correlations: [],
    };
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(responseBody), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    );
    vi.stubGlobal('fetch', fetchMock);
    const controller = new AbortController();

    const result = await fetchActiveIncidents({
      timeWindowDays: 5,
      limitPerDisaster: 4,
      signal: controller.signal,
    });

    expect(result).toEqual(responseBody);
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringMatching(/\/incidents\?time_window_days=5&limit_per_disaster=4$/),
      { signal: controller.signal },
    );
  });

  it('preserves all six hazard records and per-hazard coverage at the frontend boundary', async () => {
    const geometries: Record<DisasterType, IncidentGeometry> = {
      earthquake: {
        kind: 'point',
        coordinates: [{ latitude: 52, longitude: -170 }],
        description: null,
        source_id: 'six-hazard-fixture',
        estimated: false,
      },
      flood: {
        kind: 'point',
        coordinates: [{ latitude: 15, longitude: 105 }],
        description: null,
        source_id: 'six-hazard-fixture',
        estimated: true,
      },
      wildfire: {
        kind: 'area',
        coordinates: [
          { latitude: -1, longitude: -121 },
          { latitude: 1, longitude: -121 },
          { latitude: 1, longitude: -119 },
          { latitude: -1, longitude: -119 },
        ],
        description: null,
        source_id: 'six-hazard-fixture',
        estimated: false,
      },
      landslide: {
        kind: 'point',
        coordinates: [{ latitude: 23.5, longitude: 121 }],
        description: null,
        source_id: 'six-hazard-fixture',
        estimated: false,
      },
      tropical_cyclone: {
        kind: 'track',
        coordinates: [
          { latitude: 20, longitude: 145 },
          { latitude: 20, longitude: 155 },
        ],
        description: null,
        source_id: 'six-hazard-fixture',
        estimated: false,
      },
      volcanic_eruption: {
        kind: 'point',
        coordinates: [{ latitude: -3, longitude: 36 }],
        description: null,
        source_id: 'six-hazard-fixture',
        estimated: false,
      },
    };
    const responseBody: ActiveIncidentsSnapshot = {
      retrieved_at: '2026-08-06T03:00:00Z',
      incidents: DISASTERS.map((disaster) => incident(disaster, geometries[disaster])),
      coverage: DISASTERS.map((disaster) => ({
        disaster,
        state: disaster === 'flood' ? 'degraded' : 'events_found',
        incident_count: 1,
        providers: ['Six hazard fixture'],
        detail:
          disaster === 'flood'
            ? 'Usable flood records remain visible after a provider issue.'
            : 'One usable event record was returned.',
      })),
      warnings: ['Flood fixture coverage is intentionally degraded.'],
      correlations: [],
    };
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify(responseBody), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        }),
      ),
    );

    const result = await fetchActiveIncidents();

    expect(result).toEqual(responseBody);
    expect(result.incidents.map((item) => item.disaster)).toEqual(DISASTERS);
    expect(
      result.incidents.find((item) => item.disaster === 'flood')?.geometry,
    ).toEqual(geometries.flood);
    expect(
      Object.fromEntries(result.coverage.map((item) => [item.disaster, item.state])),
    ).toEqual({
      earthquake: 'events_found',
      flood: 'degraded',
      wildfire: 'events_found',
      landslide: 'events_found',
      tropical_cyclone: 'events_found',
      volcanic_eruption: 'events_found',
    });
    expect(result.incidents.some((item) => item.disaster === 'flood')).toBe(true);
  });

  it('surfaces a user-safe HTTP failure detail', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({ detail: 'Incident providers are unavailable.' }),
          {
            status: 503,
            headers: { 'Content-Type': 'application/json' },
          },
        ),
      ),
    );

    await expect(fetchActiveIncidents()).rejects.toThrow(
      'Incident providers are unavailable.',
    );
  });
});
