import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import type { ActiveIncident } from '@/features/incidents/model/activeIncidents';
import { SelectedIncidentSummary } from '@/features/incidents/ui/SelectedIncidentSummary';
import { TEST_INCIDENT_COUNTRY } from './fixtures/incidents';

const INCIDENT: ActiveIncident = {
  event_id: 'earthquake-1',
  disaster: 'earthquake',
  country: TEST_INCIDENT_COUNTRY,
  location: 'Aleutian earthquake fixture, United States',
  event_time: '2026-08-06T09:30:00Z',
  geometry: {
    kind: 'point',
    coordinates: [{ latitude: 52, longitude: -170 }],
    description: null,
    source_id: 'fixture-earthquakes',
    estimated: false,
  },
  measurements: [],
  provider_ids: ['fixture:earthquake-1'],
  provider_tier: 'primary',
  source_authority: 'scientific_authority',
  source: {
    source_id: 'fixture-earthquakes',
    publisher: 'Fixture Earthquake Authority',
    title: 'Fixture earthquake bulletin',
    canonical_url: 'https://earthquakes.example/events/1',
    published_at: '2026-08-06T09:35:00Z',
    updated_at: '2026-08-06T09:40:00Z',
    retrieved_at: '2026-08-06T10:00:00Z',
    snapshot_id: null,
  },
};

describe('SelectedIncidentSummary', () => {
  it('uses the monitoring snapshot as the relative-time reference', () => {
    render(
      <SelectedIncidentSummary
        incident={INCIDENT}
        snapshotRetrievedAt="2026-08-06T10:00:00Z"
        onAsk={vi.fn()}
      />,
    );

    expect(screen.getByText(/Reported 30 min ago/)).toBeVisible();
    expect(screen.queryByText(/Reported \d+ days ago/)).not.toBeInTheDocument();
  });
});
