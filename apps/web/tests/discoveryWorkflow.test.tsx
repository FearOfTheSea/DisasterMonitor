import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { useState } from 'react';
import { afterEach, expect, it, vi } from 'vitest';
import { useWorkspacePresentation } from '@/app/workspace/useWorkspacePresentation';
import type {
  ActiveIncident,
  ActiveIncidentsSnapshot,
} from '@/features/incidents/model/activeIncidents';
import { ActiveIncidentsPanel } from '@/features/incidents/ui/ActiveIncidentsPanel';
import { SelectedEventPane } from '@/features/incidents/ui/SelectedEventPane';
import { activeIncidentMapFeatures } from '@/features/map/model/activeIncidentMap';
import { createDefaultMapLayerState } from '@/features/map/model/mapLayerState';

afterEach(cleanup);

const source = {
  source_id: 'open-news',
  publisher: 'Unfamiliar News',
  title: 'Drought continues in Riverton',
  canonical_url: 'https://unfamiliar.example/story',
  published_at: '2026-10-17T10:00:00Z',
  updated_at: null,
  retrieved_at: '2026-10-17T12:00:00Z',
  snapshot_id: null,
};
const incident: ActiveIncident = {
  event_id: 'discovery:unlocated',
  disaster: 'drought',
  country: null,
  location: 'Riverton',
  event_time: null,
  event_time_basis: 'unknown',
  geometry: null,
  measurements: [],
  provider_ids: [],
  provider_tier: 'secondary',
  source_authority: 'secondary',
  source,
  verification_status: 'provisional_news_detected',
  discovery_reports: [
    {
      source,
      event_time: null,
      indexed_at: '2026-10-17T11:00:00Z',
      origin: 'wire:one',
      fatality_evidence: ['Officials report two people died.'],
    },
  ],
};
const located: ActiveIncident = {
  ...incident,
  event_id: 'discovery:located',
  disaster: 'flood',
  location: 'North Riverton',
  event_time: '2026-08-01T10:00:00Z',
  event_time_basis: 'reported',
  geometry: {
    kind: 'point',
    coordinates: [{ latitude: 12, longitude: 105 }],
    source_id: 'open-news',
    description: null,
    estimated: false,
  },
};
const snapshot: ActiveIncidentsSnapshot = {
  publication_scan: true,
  scan_status: 'completed',
  retrieved_at: '2026-10-17T12:00:00Z',
  incidents: [incident, located],
  coverage: [],
  warnings: [],
};

it('keeps old-onset scanned events on the map and unlocated events inspectable in the list', () => {
  function Workflow() {
    const [selected, select] = useState<string>();
    const view = useWorkspacePresentation({
      messages: [],
      snapshot,
      mapLayerState: createDefaultMapLayerState(),
      selectedIncidentId: selected,
    });
    expect(
      activeIncidentMapFeatures(view.mapIncidents).map((item) => item.incidentId),
    ).toEqual(['discovery:located']);
    return (
      <>
        <ActiveIncidentsPanel
          compact
          snapshot={view.displayedSnapshot}
          status="success"
          onSelectIncident={select}
          onRefresh={vi.fn()}
        />
        {view.selectedIncident ? (
          <SelectedEventPane
            incident={view.selectedIncident}
            snapshotRetrievedAt={snapshot.retrieved_at}
            onClose={() => select(undefined)}
            onAsk={vi.fn()}
            onGroundView={vi.fn()}
          />
        ) : null}
      </>
    );
  }
  render(<Workflow />);
  expect(screen.getByRole('heading', { name: 'Discovered events' })).toBeVisible();
  fireEvent.click(screen.getByRole('button', { name: 'Inspect Riverton' }));
  expect(screen.getByRole('heading', { name: 'Drought', level: 2 })).toBeVisible();
  expect(screen.getByText(/Event time unresolved. Article published:/)).toBeVisible();
  expect(screen.getByText(/Officials report two people died/)).toBeVisible();
  expect(screen.getByText(/Shared reporting origin: wire:one/)).toBeVisible();
  fireEvent.click(screen.getByRole('tab', { name: 'Evidence' }));
  expect(
    screen.getByText(/Publication time cannot target event evidence or imagery/),
  ).toBeVisible();
});

it.each(['running', 'failed', 'incomplete'] as const)(
  'does not label %s as a successful empty result',
  (state) => {
    render(
      <ActiveIncidentsPanel
        snapshot={{ ...snapshot, incidents: [], scan_status: state }}
        status="success"
        onSelectIncident={vi.fn()}
        onRefresh={vi.fn()}
      />,
    );
    expect(screen.queryByText(/A successful empty result/)).not.toBeInTheDocument();
  },
);
