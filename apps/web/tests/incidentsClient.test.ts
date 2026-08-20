import { afterEach, describe, expect, it, vi } from 'vitest';

import { fetchActiveIncidents } from '@/features/incidents/api/incidentsClient';

describe('incidentsClient', () => {
  afterEach(() => vi.unstubAllGlobals());

  it('constructs a bounded Active Incidents request', async () => {
    const responseBody = {
      retrieved_at: '2026-08-20T06:00:00Z',
      incidents: [],
      coverage: [],
      warnings: [],
    };
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(responseBody), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    );
    vi.stubGlobal('fetch', fetchMock);
    const controller = new AbortController();

    const result = await fetchActiveIncidents({
      timeWindowDays: 5,
      limitPerDisaster: 4,
      signal: controller.signal,
    });

    expect(result).toEqual(responseBody);
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringMatching(/\/incidents\?time_window_days=5&limit_per_disaster=4$/),
      { signal: controller.signal },
    );
  });

  it('surfaces a user-safe HTTP failure detail', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({ detail: 'Incident providers are unavailable.' }),
          {
            status: 503,
            headers: { 'Content-Type': 'application/json' },
          },
        ),
      ),
    );

    await expect(fetchActiveIncidents()).rejects.toThrow(
      'Incident providers are unavailable.',
    );
  });
});
