import { afterEach, describe, expect, it, vi } from 'vitest';

import {
  createIncidentWatch,
  fetchIncidentWatches,
  markIncidentWatchTimelineRead,
} from '@/features/operations/api/incidentWatches';

describe('incident watches client', () => {
  afterEach(() => vi.unstubAllGlobals());

  it('uses typed local watch endpoints', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(
        new Response('[]', {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        }),
      )
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            watch_id: 'incident-watch:1',
            disaster: 'flood',
            scope: {
              kind: 'worldwide',
              country_code: null,
              country_name: null,
            },
            enabled: true,
            refresh_interval_seconds: 900,
            created_at: '2026-08-31T08:00:00Z',
            updated_at: '2026-08-31T08:00:00Z',
            next_refresh_at: '2026-08-31T08:00:00Z',
            last_checked_at: null,
            coverage_state: null,
            unread_change_count: 0,
          }),
          { status: 201, headers: { 'Content-Type': 'application/json' } },
        ),
      )
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            watch_id: 'incident-watch:1',
            marked_read_count: 1,
            unread_change_count: 0,
          }),
          { status: 200, headers: { 'Content-Type': 'application/json' } },
        ),
      );
    vi.stubGlobal('fetch', fetchMock);

    await fetchIncidentWatches();
    await createIncidentWatch({
      disaster: 'flood',
      scope: { kind: 'worldwide' },
      refresh_interval_seconds: 900,
    });
    await markIncidentWatchTimelineRead('incident-watch:1', ['change:1']);

    expect(fetchMock).toHaveBeenNthCalledWith(
      1,
      expect.stringMatching(/\/incident-watches$/),
      expect.objectContaining({ signal: undefined }),
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      expect.stringMatching(/\/incident-watches$/),
      expect.objectContaining({ method: 'POST' }),
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      3,
      expect.stringMatching(/\/incident-watches\/incident-watch%3A1\/timeline\/read$/),
      expect.objectContaining({ method: 'POST' }),
    );
  });
});
