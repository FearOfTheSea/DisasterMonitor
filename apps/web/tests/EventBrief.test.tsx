import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';

import { EventBrief } from '@/features/event-brief/ui/EventBrief';
import type { IncidentMapRecord } from '@/features/incidents/model/activeIncidents';

const incident: IncidentMapRecord = {
  event_id: 'usgs:us7000fixture',
  physical_event_id: 'physical:earthquake:1',
  disaster: 'earthquake',
  country: {
    code: 'VNM',
    name: 'Viet Nam',
    association_basis: 'coordinate_polygon',
    distance_km: null,
  },
  location: 'Central Viet Nam',
  event_time: '2026-09-14T08:00:00Z',
  geometry: {
    kind: 'point',
    coordinates: [{ latitude: 11, longitude: 107 }],
    description: null,
    source_id: 'usgs-earthquakes',
    estimated: false,
  },
  measurements: [
    {
      kind: 'magnitude',
      value: 6.4,
      unit: null,
      source_id: 'usgs-earthquakes',
    },
  ],
  provider_ids: ['usgs:us7000fixture'],
  provider_tier: 'primary',
  source_authority: 'scientific_authority',
  source: {
    source_id: 'usgs-earthquakes',
    publisher: 'USGS',
    title: 'M 6.4 earthquake',
    canonical_url: 'https://earthquake.usgs.gov/earthquakes/eventpage/us7000fixture',
    published_at: '2026-09-14T08:00:00Z',
    updated_at: '2026-09-14T08:10:00Z',
    retrieved_at: '2026-09-14T08:15:00Z',
    snapshot_id: 'snapshot:1',
  },
};

afterEach(cleanup);

describe('EventBrief', () => {
  it('provides every evidence-native section and keeps exposure wording conservative', () => {
    render(<EventBrief incident={incident} onGroundView={() => undefined} />);

    for (const name of [
      'Identity',
      'Observations',
      'Warnings',
      'Forecast / model',
      'Exposure',
      'Humanitarian',
      'Imagery',
      'Gaps',
      'Timeline',
      'Provenance',
    ]) {
      expect(screen.getByRole('tab', { name })).toBeInTheDocument();
    }

    fireEvent.click(screen.getByRole('tab', { name: 'Exposure' }));
    expect(
      screen.getByText(/population and assets intersecting a source-backed area/i),
    ).toBeInTheDocument();
    expect(screen.getByText(/not verified as affected/i)).toBeInTheDocument();
  });

  it('shows ShakeMap measure meanings without scale conversion', () => {
    render(<EventBrief incident={incident} onGroundView={() => undefined} />);
    fireEvent.click(screen.getByRole('tab', { name: 'Forecast / model' }));

    expect(screen.getByRole('button', { name: 'MMI' })).toBeInTheDocument();
    expect(screen.getByText(/felt intensity/i)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'PGA' })).toBeInTheDocument();
    expect(screen.getByText(/peak ground acceleration.*%g/i)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'PGV' })).toBeInTheDocument();
    expect(screen.getByText(/peak ground velocity.*cm\/s/i)).toBeInTheDocument();
    expect(screen.getByText(/never converted between scales/i)).toBeInTheDocument();
  });
});
