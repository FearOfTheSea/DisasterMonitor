import { describe, expect, it } from 'vitest';

import {
  displayActiveIncidentLocation,
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
  it('uses a human-readable location for worldwide GFM acquisitions', () => {
    expect(
      displayActiveIncidentLocation(
        incident({
          location: 'CEMS GFM acquisition S1D_IW_GRDH_1SDV_20260907T155945',
          source: {
            ...incident().source,
            source_id: 'cems-gfm-floods',
          },
        }),
      ),
    ).toBe('Worldwide');
  });

  it('preserves meaningful provider locations', () => {
    expect(displayActiveIncidentLocation(incident())).toBe('Da Nang, Vietnam');
  });
});
