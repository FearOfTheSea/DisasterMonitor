import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import {
  fetchIncidentWatches,
  fetchIncidentWatchTimeline,
  markIncidentWatchTimelineRead,
} from '@/features/operations/api/incidentWatches';
import type {
  IncidentWatch,
  IncidentWatchChange,
} from '@/features/operations/model/incidentWatch';
import { FindingsCenter } from '@/features/operations/ui/FindingsCenter';
import type { ActiveIncidentsSnapshot } from '@/features/incidents/model/activeIncidents';

vi.mock('@/features/operations/api/incidentWatches', () => ({
  fetchIncidentWatches: vi.fn(),
  fetchIncidentWatchTimeline: vi.fn(),
  markIncidentWatchTimelineRead: vi.fn(),
}));

const WATCH: IncidentWatch = {
  watch_id: 'watch-1',
  disaster: 'flood',
  scope: { kind: 'country', country_code: 'VNM', country_name: 'Vietnam' },
  enabled: true,
  refresh_interval_seconds: 900,
  created_at: '2026-09-01T08:00:00Z',
  updated_at: '2026-09-01T10:00:00Z',
  next_refresh_at: '2026-09-01T10:15:00Z',
  last_checked_at: '2026-09-01T10:00:00Z',
  coverage_state: 'degraded',
  unread_change_count: 1,
};

const CHANGE: IncidentWatchChange = {
  change_id: 'change-1',
  watch_id: WATCH.watch_id,
  kind: 'new_event',
  summary: 'New exact event',
  detail: 'A source-backed event was added.',
  created_at: '2026-09-01T10:00:00Z',
  read_at: null,
  source_ids: ['fixture-source'],
  observation_id: 'observation-1',
  previous_observation_id: null,
  before_hash: null,
  after_hash: 'sha256:fixture',
  incident: {
    physical_event_id: 'physical:flood-1',
    event_id: 'flood-1',
    disaster: 'flood',
    location: 'Fixture delta',
    event_time: '2026-09-01T09:45:00Z',
    geometry: {
      kind: 'point',
      coordinates: [{ latitude: 10, longitude: 20 }],
      description: null,
      source_id: 'fixture-source',
      estimated: false,
    },
    measurements: [],
    provider_ids: ['fixture:flood-1'],
    provider_tier: 'primary',
    source_authority: 'scientific_authority',
    source: {
      source_id: 'fixture-source',
      publisher: 'Fixture Authority',
      title: 'Fixture flood',
      canonical_url: 'https://example.test/flood-1',
      published_at: '2026-09-01T09:45:00Z',
      updated_at: null,
      retrieved_at: '2026-09-01T10:00:00Z',
      snapshot_id: null,
    },
    evidence_sources: [],
  },
};

const SNAPSHOT: ActiveIncidentsSnapshot = {
  retrieved_at: '2026-09-01T10:00:00Z',
  incidents: [],
  coverage: [
    {
      disaster: 'wildfire',
      state: 'unavailable',
      incident_count: 0,
      providers: [],
      detail: 'Wildfire provider is unavailable.',
    },
  ],
  warnings: ['Active incident warning.'],
  correlations: [],
};

describe('FindingsCenter', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(fetchIncidentWatches).mockResolvedValue([WATCH]);
    vi.mocked(fetchIncidentWatchTimeline).mockResolvedValue([CHANGE]);
    vi.mocked(markIncidentWatchTimelineRead).mockResolvedValue({
      watch_id: WATCH.watch_id,
      marked_read_count: 1,
      unread_change_count: 0,
    });
  });

  it('loads deterministic findings, focuses retained geometry, and marks read via the watch API', async () => {
    const user = userEvent.setup();
    const onSelectIncident = vi.fn();
    const onWatchDataChange = vi.fn();
    render(
      <FindingsCenter
        activeSnapshot={SNAPSHOT}
        displayedIncidents={[]}
        displayedCorrelations={[]}
        onSelectIncident={onSelectIncident}
        onWatchDataChange={onWatchDataChange}
      />,
    );

    expect(await screen.findByText(CHANGE.summary)).toBeInTheDocument();
    expect(screen.getByText('Wildfire provider is unavailable.')).toBeInTheDocument();
    expect(screen.getByText('Active incident warning.')).toBeInTheDocument();
    expect(screen.getByText(/Vietnam.*Degraded/i)).toBeInTheDocument();
    expect(screen.getByText('Sources: fixture-source')).toBeInTheDocument();

    await user.click(
      screen.getByRole('button', { name: 'Focus Fixture delta on map' }),
    );
    expect(onSelectIncident).toHaveBeenCalledWith(CHANGE.incident);

    await user.click(
      screen.getByRole('button', { name: `Mark ${CHANGE.summary} read` }),
    );
    expect(markIncidentWatchTimelineRead).toHaveBeenCalledWith(WATCH.watch_id, [
      CHANGE.change_id,
    ]);
    await waitFor(() => expect(onWatchDataChange).toHaveBeenCalledOnce());
  });
});
