import { describe, expect, it } from 'vitest';

import type {
  ActiveIncident,
  DisasterType,
  IncidentGeometry,
} from '@/features/incidents/model/activeIncidents';
import { activeIncidentMapFeatures } from '@/features/map/model/activeIncidentMap';

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
});
