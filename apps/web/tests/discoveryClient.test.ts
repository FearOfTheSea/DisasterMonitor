import { afterEach, expect, it, vi } from 'vitest';
import {
  fetchDiscoveryScan,
  requestDiscoveryScan,
} from '@/features/incidents/api/discoveryClient';

afterEach(() => vi.unstubAllGlobals());

const run = {
  scan_id: '00000000-0000-4000-8000-000000000001',
  reporting_days: 7,
  interval_start: '2026-10-10T12:00:00Z',
  interval_end: '2026-10-17T12:00:00Z',
  status: 'completed',
  finished_at: '2026-10-17T12:01:00Z',
  issues: [],
  truncated: false,
  reports_seen: 0,
  unknown_publication_count: 0,
  unlocated_count: 0,
  successful_operations: 7,
  failed_operations: 0,
  snapshot: {
    retrieved_at: '2026-10-17T12:00:00Z',
    incidents: [],
    coverage: [],
    warnings: [],
  },
};

it.each([1, 3, 7, 14, 30] as const)(
  'sends the %s-day reporting choice and retains server interval',
  async (days) => {
    const fetcher = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          ...run,
          reporting_days: days,
          interval_start: new Date(
            Date.parse(run.interval_end) - days * 86_400_000,
          ).toISOString(),
        }),
      ),
    );
    vi.stubGlobal('fetch', fetcher);
    const result = await requestDiscoveryScan(days);
    expect(JSON.parse(fetcher.mock.calls[0][1].body)).toEqual({ reporting_days: days });
    expect(result.interval_end).toBe(run.interval_end);
  },
);

it('rejects invalid scan transport rather than presenting successful empty results', async () => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('{}')));
  await expect(fetchDiscoveryScan(run.scan_id)).rejects.toThrow(
    'invalid scan response',
  );
});

it('rejects a shifted or inconsistent reporting interval', async () => {
  vi.stubGlobal(
    'fetch',
    vi
      .fn()
      .mockResolvedValue(
        new Response(JSON.stringify({ ...run, interval_start: run.interval_end })),
      ),
  );
  await expect(fetchDiscoveryScan(run.scan_id)).rejects.toThrow(
    'invalid reporting interval',
  );
});
