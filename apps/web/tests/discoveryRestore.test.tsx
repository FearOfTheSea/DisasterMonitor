import { act, cleanup, renderHook, waitFor } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { useDiscoveryScan } from '@/features/incidents/hooks/useDiscoveryScan';
import type { DiscoveryScanResponse } from '@/shared/api/generated/assistant';

const clients = vi.hoisted(() => ({ fetch: vi.fn(), start: vi.fn() }));
vi.mock('@/features/incidents/api/discoveryClient', () => ({
  fetchDiscoveryScan: clients.fetch,
  requestDiscoveryScan: clients.start,
}));
const scan = {
  scan_id: '11111111-1111-4111-8111-111111111111',
  reporting_days: 30,
  status: 'completed',
  snapshot: { incidents: [] },
} as unknown as DiscoveryScanResponse;
afterEach(() => {
  cleanup();
  vi.clearAllMocks();
  window.history.replaceState(null, '', '/');
});

it('restores an explicitly referenced retained scan without starting acquisition', async () => {
  window.history.replaceState(null, '', `/?scan=${scan.scan_id}`);
  clients.fetch.mockResolvedValue(scan);
  const { result } = renderHook(() => useDiscoveryScan());
  await waitFor(() => expect(result.current.run?.scan_id).toBe(scan.scan_id));
  expect(result.current.days).toBe(30);
  expect(clients.start).not.toHaveBeenCalled();
});

it('does not let a late restored scan replace a newly requested scan', async () => {
  window.history.replaceState(null, '', `/?scan=${scan.scan_id}`);
  let finish!: (value: DiscoveryScanResponse) => void;
  clients.fetch.mockReturnValue(
    new Promise((resolve) => {
      finish = resolve;
    }),
  );
  const next = { ...scan, scan_id: '22222222-2222-4222-8222-222222222222' };
  clients.start.mockResolvedValue(next);
  const { result } = renderHook(() => useDiscoveryScan());
  await act(() => result.current.start());
  await act(async () => {
    finish(scan);
  });
  expect(result.current.run?.scan_id).toBe(next.scan_id);
  expect(new URLSearchParams(window.location.search).get('scan')).toBe(next.scan_id);
});

it('finds a named event inside a regional report passage', async () => {
  clients.start.mockResolvedValue({
    ...scan,
    snapshot: {
      incidents: [
        {
          event_id: 'named-storm',
          location: 'Western coast',
          disaster: 'tropical_cyclone',
          source: { title: 'Regional situation update', publisher: 'Agency' },
          discovery_reports: [{ mention_excerpt: 'Hurricane Arlen damaged homes.' }],
        },
      ],
    },
  });
  const { result } = renderHook(() => useDiscoveryScan());
  await act(() => result.current.start());
  act(() => result.current.setSearch('Arlen'));
  expect(result.current.snapshot?.incidents.map((i) => i.event_id)).toEqual([
    'named-storm',
  ]);
});
