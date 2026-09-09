import { cleanup, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';

import type {
  ActiveIncident,
  ActiveIncidentsSnapshot,
  DisasterType,
} from '@/features/incidents/model/activeIncidents';
import { ActiveIncidentsPanel } from '@/features/incidents/ui/ActiveIncidentsPanel';
import { TEST_INCIDENT_COUNTRY } from './fixtures/incidents';

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
  country: TEST_INCIDENT_COUNTRY,
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
          : disaster === 'landslide'
            ? 'No configured worldwide provider is available for landslides.'
            : 'Configured providers returned no matching records; this is not evidence that no disaster occurred.',
    })),
    warnings: ['Fixture provider returned a partial response.'],
    correlations: [],
  };
}

afterEach(cleanup);

describe('ActiveIncidentsPanel', () => {
  it('labels provisional news incidents and exposes the detection clock', async () => {
    const user = userEvent.setup();
    const provisional: ActiveIncident = {
      ...INCIDENT,
      event_id: 'news-candidate:antalya',
      country: null,
      location: 'Antalya, Turkey',
      geometry: null,
      provider_tier: 'secondary',
      source_authority: 'secondary',
      verification_status: 'provisional_news_detected',
      detection: {
        news_break_at: '2026-08-20T04:00:00Z',
        first_observed_at: '2026-08-20T04:10:00Z',
        candidate_created_at: '2026-08-20T04:11:00Z',
        verified_at: null,
        monitor_visible_at: '2026-08-20T04:15:00Z',
        assistant_ready_at: '2026-08-20T04:15:00Z',
      },
    };

    render(
      <ActiveIncidentsPanel
        snapshot={snapshot([provisional])}
        status="success"
        onSelectIncident={vi.fn()}
        onRefresh={vi.fn()}
      />,
    );

    expect(screen.getByText('Provisional news report')).toBeVisible();
    expect(screen.getByText('Authoritative confirmation pending')).toBeVisible();
    await user.click(screen.getByText('Source details'));
    expect(screen.getByText(/News first published:/)).toBeVisible();
    expect(screen.getByText(/Visible in monitoring:/)).toBeVisible();
  });

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
      screen.getByRole('heading', { name: "What's happening" }),
    ).toBeInTheDocument();
    expect(screen.getByText('Recent events reported by trusted sources')).toBeVisible();
    expect(screen.getAllByTestId('incident-coverage')).toHaveLength(6);
    expect(screen.getByText('Degraded')).toBeInTheDocument();
    expect(screen.getByText('Unavailable')).toBeInTheDocument();
    expect(screen.getAllByText('No matching records')).toHaveLength(4);
    const coverageItems = screen.getAllByTestId('incident-coverage');
    expect(within(coverageItems[0]).getByText('Earthquake')).toBeInTheDocument();
    expect(
      within(coverageItems[0]).getByText('No matching records'),
    ).toBeInTheDocument();
    expect(coverageItems[0]).toHaveTextContent(
      'this is not evidence that no disaster occurred',
    );
    expect(within(coverageItems[2]).getByText('Wildfire')).toBeInTheDocument();
    expect(within(coverageItems[2]).getByText('Degraded')).toBeInTheDocument();
    expect(coverageItems[2]).toHaveTextContent(
      'Usable wildfire records were retained after a provider issue.',
    );
    expect(within(coverageItems[3]).getByText('Landslide')).toBeInTheDocument();
    expect(within(coverageItems[3]).getByText('Unavailable')).toBeInTheDocument();
    expect(screen.getByText('Some gaps')).not.toBeVisible();
    expect(
      screen.getByText('Fixture provider returned a partial response.'),
    ).toBeInTheDocument();
    expect(screen.getByText('Fixture Fire Authority')).not.toBeVisible();
    expect(screen.getByText('Primary tier')).not.toBeVisible();
    expect(screen.getByText('Scientific authority')).not.toBeVisible();
    expect(screen.getByText('Selected')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Focus Japan on map' })).toHaveAttribute(
      'aria-pressed',
      'true',
    );
    expect(screen.getAllByText(/Source updated/)).toHaveLength(2);
    expect(
      screen.getByRole('link', { name: 'Fixture wildfire perimeter' }),
    ).toHaveAttribute('href', 'https://wildfires.example/incidents/fire-1');

    await user.click(screen.getByText('Source details'));
    expect(screen.getByText('Fixture Fire Authority')).toBeVisible();
    expect(screen.getByText('Primary tier')).toBeVisible();
    expect(screen.getByText('Scientific authority')).toBeVisible();

    await user.click(screen.getByRole('button', { name: 'Focus Japan on map' }));
    expect(onSelectIncident).toHaveBeenCalledWith('fire-1');
  });

  it('summarizes source coverage before revealing provider detail', async () => {
    const user = userEvent.setup();
    render(
      <ActiveIncidentsPanel
        snapshot={snapshot()}
        status="success"
        selectedIncidentId={undefined}
        onSelectIncident={vi.fn()}
        onRefresh={vi.fn()}
      />,
    );

    expect(screen.getByText('5 source networks checked')).toBeVisible();
    expect(screen.getByText('View coverage')).toBeVisible();
    expect(screen.getAllByTestId('incident-coverage')[0]).not.toBeVisible();

    await user.click(screen.getByText('View coverage'));
    expect(screen.getAllByTestId('incident-coverage')[0]).toBeVisible();
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

  it('uses the associated country and keeps the flood event ID in the details', () => {
    const floodEventId =
      'cems-gfm:sentinel-acquisition:S1C_IW_GRDH_1SDV_20260907T104635_20260907T104701_009340_01293B_C236';
    const longFloodIncident: ActiveIncident = {
      ...INCIDENT,
      event_id: floodEventId,
      disaster: 'flood',
      country: {
        code: 'ITA',
        name: 'Italy',
        association_basis: 'nearby_boundary',
        distance_km: 10.8,
      },
      location: `CEMS GFM acquisition ${floodEventId.slice(floodEventId.indexOf(':') + 1)}`,
      source: {
        ...INCIDENT.source,
        source_id: 'cems-gfm-floods',
      },
    };

    render(
      <ActiveIncidentsPanel
        snapshot={snapshot([longFloodIncident])}
        status="success"
        selectedIncidentId={undefined}
        onSelectIncident={vi.fn()}
        onRefresh={vi.fn()}
      />,
    );

    const button = screen.getByRole('button', { name: 'Focus Italy on map' });
    expect(button.querySelector('.incident-card-location')).toHaveTextContent('Italy');
    expect(button).toHaveTextContent('10.8 km from mapped boundary');
    expect(button.closest('.incident-card')).toHaveTextContent(
      `Event ID: ${floodEventId}`,
    );
  });

  it('uses a source-backed flood country in the card title', () => {
    const floodEventId = 'cems-gfm:sentinel-acquisition:japan-flood-1';
    const floodIncident: ActiveIncident = {
      ...INCIDENT,
      event_id: floodEventId,
      disaster: 'flood',
      location: 'Japan',
      source: {
        ...INCIDENT.source,
        source_id: 'cems-gfm-floods',
      },
    };

    render(
      <ActiveIncidentsPanel
        snapshot={snapshot([floodIncident])}
        status="success"
        selectedIncidentId={undefined}
        onSelectIncident={vi.fn()}
        onRefresh={vi.fn()}
      />,
    );

    expect(
      screen.getByRole('button', { name: 'Focus Japan on map' }),
    ).toBeInTheDocument();
    expect(screen.getByText('Japan')).toHaveClass('incident-card-location');
    expect(screen.getByText(`Event ID: ${floodEventId}`)).toBeInTheDocument();
  });

  it('renders bounded compound-hazard context with its non-causation limit', () => {
    const correlated = snapshot();
    correlated.correlations = [
      {
        correlation_id: 'compound-correlation:v1:fixture',
        rule_id: 'compound-hazard:tropical-cyclone-flood:v1',
        relationship: 'spatiotemporal_association',
        first_event_id: 'cyclone-1',
        first_physical_event_id: 'physical:cyclone-1',
        first_disaster: 'tropical_cyclone',
        second_event_id: 'flood-1',
        second_physical_event_id: 'physical:flood-1',
        second_disaster: 'flood',
        distance_km: 82.4,
        time_delta_seconds: 18_000,
        source_ids: ['gdacs-tropical-cyclones', 'cems-gfm-floods'],
        summary:
          'Tropical cyclone cyclone-1 and flood flood-1 are approximately 82.4 km and 5 hours apart.',
        limitation: 'Spatial and temporal proximity does not establish causation.',
      },
    ];

    const { rerender } = render(
      <ActiveIncidentsPanel
        snapshot={correlated}
        status="success"
        selectedIncidentId={undefined}
        onSelectIncident={vi.fn()}
        onRefresh={vi.fn()}
      />,
    );

    const section = screen.getByRole('region', { name: 'Related hazard context' });
    expect(section).toHaveTextContent('Tropical cyclone → Flood');
    expect(section).toHaveTextContent('82.4 km');
    expect(section).toHaveTextContent('5 hours');
    expect(section).toHaveTextContent('gdacs-tropical-cyclones');
    expect(section).toHaveTextContent(
      'Spatial and temporal proximity does not establish causation.',
    );

    rerender(
      <ActiveIncidentsPanel
        snapshot={snapshot()}
        status="success"
        selectedIncidentId={undefined}
        onSelectIncident={vi.fn()}
        onRefresh={vi.fn()}
      />,
    );
    expect(
      screen.queryByRole('region', { name: 'Related hazard context' }),
    ).not.toBeInTheDocument();
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
        displayTimeWindow="1h"
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
    expect(screen.getByText(/1h display window/i)).toHaveTextContent(
      'Provider coverage above is unchanged',
    );
  });

  it('keeps coverage freshness from the unfiltered snapshot while filtering records', () => {
    const view = render(
      <ActiveIncidentsPanel
        snapshot={snapshot([])}
        coverageSnapshot={snapshot([INCIDENT])}
        status="success"
        displayTimeWindow="1h"
        selectedIncidentId={undefined}
        onSelectIncident={vi.fn()}
        onRefresh={vi.fn()}
      />,
    );

    const panel = within(view.container);
    expect(panel.getByText(/fixture-wildfires.*Source updated/)).toBeInTheDocument();
    expect(
      panel.getByText('No incident records matched this bounded retrieval.'),
    ).toBeInTheDocument();
    expect(panel.getByText(/Provider coverage above is unchanged/)).toBeVisible();
  });
});

it('searches loaded locations and sources without changing provider coverage', async () => {
  const user = userEvent.setup();
  render(
    <ActiveIncidentsPanel
      snapshot={snapshot()}
      status="success"
      onSelectIncident={vi.fn()}
      onRefresh={vi.fn()}
    />,
  );
  const search = screen.getByRole('searchbox', { name: 'Search locations or sources' });
  await user.type(search, 'missing place');
  expect(
    screen.queryByRole('button', { name: 'Focus Japan on map' }),
  ).not.toBeInTheDocument();
  expect(screen.getByText('No loaded records match your search.')).toBeVisible();
  expect(screen.getByText('View coverage')).toBeVisible();
  await user.clear(search);
  await user.type(search, 'fire authority');
  expect(screen.getByRole('button', { name: 'Focus Japan on map' })).toBeVisible();
});

it('emits explicit server-side view and hazard filters', async () => {
  const user = userEvent.setup();
  const onViewChange = vi.fn();
  const onHazardChange = vi.fn();
  render(
    <ActiveIncidentsPanel
      snapshot={snapshot()}
      status="success"
      view="recent"
      onViewChange={onViewChange}
      onHazardChange={onHazardChange}
      onSelectIncident={vi.fn()}
      onRefresh={vi.fn()}
    />,
  );

  await user.selectOptions(
    screen.getByRole('combobox', { name: 'Incident view' }),
    'ongoing',
  );
  await user.selectOptions(
    screen.getByRole('combobox', { name: 'Hazard filter' }),
    'wildfire',
  );

  expect(onViewChange).toHaveBeenCalledWith('ongoing');
  expect(onHazardChange).toHaveBeenCalledWith('wildfire');
});
