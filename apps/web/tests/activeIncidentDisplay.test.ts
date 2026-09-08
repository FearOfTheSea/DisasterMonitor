import { describe, expect, it } from 'vitest';

import {
  displayActiveIncidentCountry,
  displayActiveIncidentContext,
  type ActiveIncident,
} from '@/features/incidents/model/activeIncidents';

function incident(overrides: Partial<ActiveIncident> = {}): ActiveIncident {
  return {
    event_id: 'event-1',
    disaster: 'flood',
    location: 'Da Nang, Vietnam',
    event_time: '2026-09-07T10:00:00Z',
    geometry: null,
    measurements: [],
    provider_ids: ['event-1'],
    provider_tier: 'primary',
    source_authority: 'scientific_authority',
    country: {
      code: 'VNM',
      name: 'Vietnam',
      association_basis: 'coordinate_polygon',
      distance_km: null,
    },
    source: {
      source_id: 'provider',
      publisher: 'Provider',
      title: 'Incident',
      canonical_url: 'https://example.test/incident',
      published_at: null,
      updated_at: null,
      retrieved_at: '2026-09-07T10:05:00Z',
      snapshot_id: null,
    },
    ...overrides,
  };
}

describe('active incident display', () => {
  it('uses the associated country instead of a technical provider location', () => {
    const technicalIncident = incident({
      location: 'CEMS GFM acquisition S1D_IW_GRDH_1SDV_20260907T155945',
      country: {
        code: 'ITA',
        name: 'Italy',
        association_basis: 'nearby_boundary',
        distance_km: 10.8,
      },
      source: {
        ...incident().source,
        source_id: 'cems-gfm-floods',
      },
    });

    expect(displayActiveIncidentCountry(technicalIncident)).toBe('Italy');
    expect(displayActiveIncidentContext(technicalIncident)).toBe(
      '10.8 km from mapped boundary',
    );
  });

  it('preserves meaningful provider locations', () => {
    expect(displayActiveIncidentCountry(incident())).toBe('Vietnam');
    expect(displayActiveIncidentContext(incident())).toBe('Da Nang, Vietnam');
  });
});
