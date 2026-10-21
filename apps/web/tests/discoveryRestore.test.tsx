import { act, cleanup, renderHook, waitFor } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { useDiscoveryScan } from '@/features/incidents/hooks/useDiscoveryScan';
import type { DiscoveryScanResponse } from '@/shared/api/generated/assistant';
import { HttpResponseError } from '@/shared/api/http';

const clients = vi.hoisted(() => ({ fetch: vi.fn(), start: vi.fn(), resume: vi.fn() }));
vi.mock('@/features/incidents/api/discoveryClient', () => ({
  fetchDiscoveryScan: clients.fetch,
  requestDiscoveryScan: clients.start,
  continueDiscoveryScan: clients.resume,
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

it.each([
  new DOMException('signal timed out', 'TimeoutError'),
  new TypeError('Failed to fetch'),
])(
  'reads saved status after a lost Continue response without repeating the mutation (%s)',
  async (error) => {
    window.history.replaceState(null, '', `/?scan=${scan.scan_id}`);
    const retained = { ...scan, status: 'incomplete' };
    const running = { ...scan, status: 'running' };
    clients.fetch.mockResolvedValueOnce(retained).mockResolvedValue(running);
    clients.resume.mockRejectedValue(error);
    const { result } = renderHook(() => useDiscoveryScan());
    await waitFor(() => expect(result.current.run?.status).toBe('incomplete'));
    await act(() => result.current.continueCollection());
    expect(result.current.run?.status).toBe('running');
    expect(result.current.error).toBeUndefined();
    expect(clients.resume).toHaveBeenCalledOnce();
    expect(clients.fetch).toHaveBeenCalledTimes(2);
    expect(clients.fetch.mock.calls[1][1]).not.toBe(clients.resume.mock.calls[0][1]);
    expect(clients.start).not.toHaveBeenCalled();
  },
);

it('keeps a definite Continue rejection visible without a recovery request', async () => {
  window.history.replaceState(null, '', `/?scan=${scan.scan_id}`);
  clients.fetch.mockResolvedValue({ ...scan, status: 'incomplete' });
  clients.resume.mockRejectedValue(
    new HttpResponseError('Storage capacity reached.', 507),
  );
  const { result } = renderHook(() => useDiscoveryScan());
  await waitFor(() => expect(result.current.run?.status).toBe('incomplete'));
  await act(() => result.current.continueCollection());
  expect(result.current.error).toBe('Storage capacity reached.');
  expect(clients.fetch).toHaveBeenCalledOnce();
  expect(clients.resume).toHaveBeenCalledOnce();
});

it('does not restore a cleared scan when a continuation status read arrives late', async () => {
  window.history.replaceState(null, '', `/?scan=${scan.scan_id}`);
  let finish!: (value: DiscoveryScanResponse) => void;
  clients.fetch
    .mockResolvedValueOnce({ ...scan, status: 'incomplete' })
    .mockReturnValueOnce(
      new Promise((resolve) => {
        finish = resolve;
      }),
    );
  clients.resume.mockRejectedValue(
    new DOMException('signal timed out', 'TimeoutError'),
  );
  const { result } = renderHook(() => useDiscoveryScan());
  await waitFor(() => expect(result.current.run?.status).toBe('incomplete'));
  let continuing!: Promise<void>;
  await act(async () => {
    continuing = result.current.continueCollection();
  });
  await waitFor(() => expect(clients.fetch).toHaveBeenCalledTimes(2));
  act(() => result.current.clear());
  await act(async () => {
    finish({ ...scan, status: 'running' });
    await continuing;
  });
  expect(result.current.run).toBeUndefined();
  expect(new URLSearchParams(window.location.search).has('scan')).toBe(false);
});
