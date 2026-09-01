import { render, screen, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import type {
  ActiveIncident,
  ActiveIncidentsSnapshot,
  DisasterType,
} from '@/features/incidents/model/activeIncidents';
import { IncidentCoverageStatus } from '@/features/incidents/ui/IncidentCoverageStatus';

const DISASTERS: DisasterType[] = [
  'earthquake',
  'flood',
  'wildfire',
  'landslide',
  'tropical_cyclone',
  'volcanic_eruption',
];

const INCIDENT: ActiveIncident = {
  event_id: 'earthquake-1',
  disaster: 'earthquake',
  location: 'Fixture region',
  event_time: '2026-09-01T10:00:00Z',
  geometry: null,
  measurements: [],
  provider_ids: ['usgs:earthquake-1'],
  provider_tier: 'primary',
  source_authority: 'scientific_authority',
  source: {
    source_id: 'usgs-earthquakes',
    publisher: 'USGS',
    title: 'Fixture earthquake',
    canonical_url: 'https://example.test/earthquake-1',
    published_at: '2026-09-01T10:01:00Z',
    updated_at: '2026-09-01T10:05:00Z',
    retrieved_at: '2026-09-01T10:06:00Z',
    snapshot_id: null,
  },
};

function snapshot(): ActiveIncidentsSnapshot {
  const states = [
    'events_found',
    'no_matching_records',
    'degraded',
    'unavailable',
    'no_matching_records',
    'no_matching_records',
  ] as const;
  return {
    retrieved_at: '2026-09-01T10:10:00Z',
    incidents: [INCIDENT],
    coverage: DISASTERS.map((disaster, index) => ({
      disaster,
      state: states[index],
      incident_count: disaster === 'earthquake' ? 1 : 0,
      providers:
        disaster === 'landslide' ? [] : [`${disaster}-provider`, 'shared-provider'],
      detail: `${disaster} fixture coverage detail.`,
    })),
    warnings: ['A fixture provider returned a partial response.'],
  };
}

describe('IncidentCoverageStatus', () => {
  it('keeps successful-empty, degraded, and unavailable coverage visibly distinct', () => {
    render(<IncidentCoverageStatus snapshot={snapshot()} />);

    expect(screen.getByText(/Snapshot retrieved:/)).toHaveTextContent(
      new Date('2026-09-01T10:10:00Z').toLocaleString(),
    );
    const items = screen.getAllByTestId('incident-coverage');
    expect(items).toHaveLength(6);
    expect(within(items[0]).getByText('Events found')).toBeInTheDocument();
    expect(within(items[1]).getByText('No matching records')).toBeInTheDocument();
    expect(within(items[2]).getByText('Degraded')).toBeInTheDocument();
    expect(within(items[3]).getByText('Unavailable')).toBeInTheDocument();
    expect(items[1]).toHaveTextContent('flood-provider');
    expect(items[3]).toHaveTextContent('No providers reported');
    expect(items[0]).toHaveTextContent('Source updated');
    expect(items[0]).toHaveTextContent(
      new Date('2026-09-01T10:05:00Z').toLocaleString(),
    );
    expect(screen.getByText('Coverage is partial')).toBeInTheDocument();
    expect(
      screen.getByText('A fixture provider returned a partial response.'),
    ).toBeInTheDocument();
    expect(screen.getByText(/not disaster claims/i)).toBeInTheDocument();
  });
});
