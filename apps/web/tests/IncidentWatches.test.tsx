import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import {
  createIncidentWatch,
  deleteIncidentWatch,
  fetchIncidentWatches,
  fetchIncidentWatchTimeline,
  markIncidentWatchTimelineRead,
  setIncidentWatchEnabled,
} from '@/features/operations/api/incidentWatches';
import type {
  IncidentWatch,
  IncidentWatchChange,
} from '@/features/operations/model/incidentWatch';
import { IncidentWatches } from '@/features/operations/ui/IncidentWatches';

vi.mock('@/features/operations/api/incidentWatches', () => ({
  createIncidentWatch: vi.fn(),
  deleteIncidentWatch: vi.fn(),
  fetchIncidentWatches: vi.fn(),
  fetchIncidentWatchTimeline: vi.fn(),
  markIncidentWatchTimelineRead: vi.fn(),
  setIncidentWatchEnabled: vi.fn(),
}));

const WATCH: IncidentWatch = {
  watch_id: 'incident-watch:1',
  disaster: 'flood',
  scope: {
    kind: 'country',
    country_code: 'VNM',
    country_name: 'Vietnam',
  },
  enabled: true,
  refresh_interval_seconds: 900,
  created_at: '2026-08-31T08:00:00Z',
  updated_at: '2026-08-31T08:00:00Z',
  next_refresh_at: '2026-08-31T08:15:00Z',
  last_checked_at: '2026-08-31T08:00:00Z',
  coverage_state: 'degraded',
  unread_change_count: 1,
};

const CHANGE: IncidentWatchChange = {
  change_id: 'incident-watch-change:1',
  watch_id: WATCH.watch_id,
  kind: 'new_event',
  summary: 'New flood event discovered',
  detail: 'A new physical event appeared in the bounded provider result.',
  created_at: '2026-08-31T08:00:00Z',
  read_at: null,
  source_ids: ['fixture-flood-source'],
  observation_id: 'incident-watch-observation:1',
  previous_observation_id: null,
  before_hash: null,
  after_hash: `sha256:${'a'.repeat(64)}`,
  incident: {
    physical_event_id: 'watch-event:fixture-flood-source:flood-1',
    event_id: 'flood-1',
    disaster: 'flood',
    location: 'Fixture delta',
    event_time: '2026-08-31T07:45:00Z',
    geometry: {
      kind: 'point',
      coordinates: [{ latitude: 10.5, longitude: 106.5 }],
      description: null,
      source_id: 'fixture-flood-source',
      estimated: false,
    },
    measurements: [],
    provider_ids: ['fixture:flood-1'],
    provider_tier: 'primary',
    source_authority: 'scientific_authority',
    source: {
      source_id: 'fixture-flood-source',
      publisher: 'Fixture Authority',
      title: 'Fixture flood event',
      canonical_url: 'https://fixture.example/flood-1',
      published_at: '2026-08-31T07:45:00Z',
      updated_at: '2026-08-31T07:50:00Z',
      retrieved_at: '2026-08-31T08:00:00Z',
      snapshot_id: null,
    },
    evidence_sources: [],
  },
};

describe('IncidentWatches', () => {
  afterEach(cleanup);

  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(fetchIncidentWatches).mockResolvedValue([WATCH]);
    vi.mocked(fetchIncidentWatchTimeline).mockResolvedValue([CHANGE]);
    vi.mocked(setIncidentWatchEnabled).mockResolvedValue({
      ...WATCH,
      enabled: false,
    });
    vi.mocked(markIncidentWatchTimelineRead).mockResolvedValue({
      watch_id: WATCH.watch_id,
      unread_change_count: 0,
      marked_read_count: 1,
    });
    vi.mocked(deleteIncidentWatch).mockResolvedValue(undefined);
    vi.mocked(createIncidentWatch).mockResolvedValue({
      ...WATCH,
      watch_id: 'incident-watch:2',
      scope: { kind: 'worldwide', country_code: null, country_name: null },
      unread_change_count: 0,
      coverage_state: null,
      last_checked_at: null,
    });
  });

  it('shows loading and honest empty states', async () => {
    let resolve: ((value: IncidentWatch[]) => void) | undefined;
    vi.mocked(fetchIncidentWatches).mockReturnValue(
      new Promise((next) => {
        resolve = next;
      }),
    );
    render(<IncidentWatches onSelectIncident={vi.fn()} />);

    expect(screen.getByRole('status')).toHaveTextContent('Loading incident watches');
    resolve?.([]);

    expect(
      await screen.findByText('No incident watches have been created.'),
    ).toBeInTheDocument();
    expect(screen.getByText(/bounded monitoring/i)).toBeInTheDocument();
  });

  it('shows degraded coverage, unread timeline, map selection, read, toggle, delete', async () => {
    const user = userEvent.setup();
    const onSelectIncident = vi.fn();
    render(<IncidentWatches onSelectIncident={onSelectIncident} />);

    expect(await screen.findByText('Vietnam')).toBeInTheDocument();
    expect(screen.getByText('Degraded')).toBeInTheDocument();
    expect(screen.getByText('1 unread')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Show timeline for Vietnam' }));
    expect(await screen.findByText('New flood event discovered')).toBeInTheDocument();
    expect(screen.getByText('Fixture Authority')).toBeInTheDocument();
    expect(screen.getByText('Sources: fixture-flood-source')).toBeInTheDocument();

    await user.click(
      screen.getByRole('button', { name: 'Focus Fixture delta on map' }),
    );
    expect(onSelectIncident).toHaveBeenCalledWith(CHANGE.incident);

    await user.click(screen.getByRole('button', { name: 'Mark timeline read' }));
    await waitFor(() =>
      expect(markIncidentWatchTimelineRead).toHaveBeenCalledWith(WATCH.watch_id, [
        CHANGE.change_id,
      ]),
    );
    expect(await screen.findByText('0 unread')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Disable Vietnam watch' }));
    expect(setIncidentWatchEnabled).toHaveBeenCalledWith(WATCH.watch_id, false);
    expect(await screen.findByText('Disabled')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Delete Vietnam watch' }));
    await waitFor(() =>
      expect(deleteIncidentWatch).toHaveBeenCalledWith(WATCH.watch_id),
    );
    expect(
      await screen.findByText('No incident watches have been created.'),
    ).toBeInTheDocument();
  });

  it('creates a worldwide single-disaster watch', async () => {
    const user = userEvent.setup();
    vi.mocked(fetchIncidentWatches).mockResolvedValue([]);
    render(<IncidentWatches onSelectIncident={vi.fn()} />);

    await screen.findByText('No incident watches have been created.');
    await user.selectOptions(screen.getByLabelText('Watch disaster'), 'wildfire');
    await user.selectOptions(screen.getByLabelText('Watch scope'), 'worldwide');
    await user.selectOptions(screen.getByLabelText('Refresh interval'), '900');
    await user.click(screen.getByRole('button', { name: 'Create watch' }));

    await waitFor(() =>
      expect(createIncidentWatch).toHaveBeenCalledWith({
        disaster: 'wildfire',
        scope: { kind: 'worldwide' },
        refresh_interval_seconds: 900,
      }),
    );
  });
});
