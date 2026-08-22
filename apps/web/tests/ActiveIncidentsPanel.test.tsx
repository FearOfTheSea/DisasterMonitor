import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import type {
  ActiveIncident,
  ActiveIncidentsSnapshot,
  DisasterType,
} from '@/features/incidents/model/activeIncidents';
import { ActiveIncidentsPanel } from '@/features/incidents/ui/ActiveIncidentsPanel';

const DISASTERS: DisasterType[] = [
  'earthquake',
  'flood',
  'wildfire',
  'landslide',
  'tropical_cyclone',
  'volcanic_eruption',
];

const INCIDENT: ActiveIncident = {
  event_id: 'fire-1',
  disaster: 'wildfire',
  location: 'Fixture reserve',
  event_time: '2026-08-20T03:00:00Z',
  geometry: {
    kind: 'point',
    coordinates: [{ latitude: 10.5, longitude: 20.25 }],
    description: null,
    source_id: 'fixture-wildfires',
    estimated: false,
  },
  measurements: [],
  provider_ids: ['fixture:fire-1'],
  provider_tier: 'primary',
  source_authority: 'scientific_authority',
  source: {
    source_id: 'fixture-wildfires',
    publisher: 'Fixture Fire Authority',
    title: 'Fixture wildfire perimeter',
    canonical_url: 'https://wildfires.example/incidents/fire-1',
    published_at: '2026-08-20T04:00:00Z',
    updated_at: '2026-08-20T05:00:00Z',
    retrieved_at: '2026-08-20T06:00:00Z',
    snapshot_id: null,
  },
};

function snapshot(incidents: ActiveIncident[] = [INCIDENT]): ActiveIncidentsSnapshot {
  return {
    retrieved_at: '2026-08-20T06:00:00Z',
    incidents,
    coverage: DISASTERS.map((disaster) => ({
      disaster,
      state:
        disaster === 'wildfire'
          ? 'degraded'
          : disaster === 'landslide'
            ? 'unavailable'
            : 'no_matching_records',
      incident_count: disaster === 'wildfire' ? incidents.length : 0,
      providers: disaster === 'landslide' ? [] : ['Fixture provider'],
      detail:
        disaster === 'wildfire'
          ? 'Usable wildfire records were retained after a provider issue.'
          : 'No usable matching records were returned.',
    })),
    warnings: ['Fixture provider returned a partial response.'],
  };
}

describe('ActiveIncidentsPanel', () => {
  it('renders all coverage states, source metadata, warnings, and selection', async () => {
    const user = userEvent.setup();
    const onSelectIncident = vi.fn();
    render(
      <ActiveIncidentsPanel
        snapshot={snapshot()}
        status="success"
        selectedIncidentId="fire-1"
        onSelectIncident={onSelectIncident}
        onRefresh={vi.fn()}
      />,
    );

    expect(
      screen.getByRole('heading', { name: 'Active incidents' }),
    ).toBeInTheDocument();
    expect(screen.getAllByTestId('incident-coverage')).toHaveLength(6);
    expect(screen.getByText('Degraded')).toBeInTheDocument();
    expect(screen.getByText('Unavailable')).toBeInTheDocument();
    expect(screen.getAllByText('No matching records')).toHaveLength(4);
    expect(screen.getByText('Coverage is partial')).toBeInTheDocument();
    expect(
      screen.getByText('Fixture provider returned a partial response.'),
    ).toBeInTheDocument();
    expect(screen.getByText('Fixture Fire Authority')).toBeInTheDocument();
    expect(screen.getByText('Primary tier')).toBeInTheDocument();
    expect(screen.getByText('Scientific authority')).toBeInTheDocument();
    expect(screen.getByText('Selected')).toBeInTheDocument();
    expect(
      screen.getByRole('button', { name: 'Focus Fixture reserve on map' }),
    ).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByText(/Source updated/)).toBeInTheDocument();
    expect(
      screen.getByRole('link', { name: 'Fixture wildfire perimeter' }),
    ).toHaveAttribute('href', 'https://wildfires.example/incidents/fire-1');

    await user.click(
      screen.getByRole('button', { name: 'Focus Fixture reserve on map' }),
    );
    expect(onSelectIncident).toHaveBeenCalledWith('fire-1');
  });

  it('labels estimated geometry without adding a long explanation', () => {
    const estimatedIncident: ActiveIncident = {
      ...INCIDENT,
      event_id: 'flood-1',
      disaster: 'flood',
      location: 'Japan',
      geometry: {
        kind: 'point',
        coordinates: [{ latitude: 32.5, longitude: 133.5 }],
        description: null,
        source_id: 'cems-gfm-floods',
        estimated: true,
      },
    };
    render(
      <ActiveIncidentsPanel
        snapshot={snapshot([estimatedIncident])}
        status="success"
        selectedIncidentId={undefined}
        onSelectIncident={vi.fn()}
        onRefresh={vi.fn()}
      />,
    );

    expect(screen.getByText('estimated')).toBeInTheDocument();
  });

  it('shows loading, failed, and successful-empty states honestly', () => {
    const { rerender } = render(
      <ActiveIncidentsPanel
        status="loading"
        selectedIncidentId={undefined}
        onSelectIncident={vi.fn()}
        onRefresh={vi.fn()}
      />,
    );
    expect(screen.getByRole('status')).toHaveTextContent('Loading active incidents');

    rerender(
      <ActiveIncidentsPanel
        status="error"
        error="Incident providers failed."
        selectedIncidentId={undefined}
        onSelectIncident={vi.fn()}
        onRefresh={vi.fn()}
      />,
    );
    expect(screen.getByRole('alert')).toHaveTextContent('Incident providers failed.');

    rerender(
      <ActiveIncidentsPanel
        snapshot={snapshot([])}
        status="success"
        selectedIncidentId={undefined}
        onSelectIncident={vi.fn()}
        onRefresh={vi.fn()}
      />,
    );
    expect(
      screen.getByText('No incident records matched this bounded retrieval.'),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/does not prove that no disaster occurred/i),
    ).toBeInTheDocument();
  });
});
