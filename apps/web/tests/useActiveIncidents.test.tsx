import { act, cleanup, renderHook, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { fetchActiveIncidents } from '@/features/incidents/api/incidentsClient';
import { useActiveIncidents } from '@/features/incidents/hooks/useActiveIncidents';
import type { ActiveIncidentsSnapshot } from '@/features/incidents/model/activeIncidents';

vi.mock('@/features/incidents/api/incidentsClient', () => ({
  fetchActiveIncidents: vi.fn(),
}));

function snapshot(retrievedAt: string): ActiveIncidentsSnapshot {
  return {
    retrieved_at: retrievedAt,
    incidents: [],
    coverage: [],
    warnings: [],
  };
}

describe('useActiveIncidents', () => {
  afterEach(() => cleanup());
  beforeEach(() => {
    vi.clearAllMocks();
    window.localStorage.clear();
  });

  it('loads on first render and exposes an explicit manual refresh', async () => {
    let resolveInitial: ((value: ActiveIncidentsSnapshot) => void) | undefined;
    vi.mocked(fetchActiveIncidents)
      .mockReturnValueOnce(
        new Promise((resolve) => {
          resolveInitial = resolve;
        }),
      )
      .mockResolvedValueOnce(snapshot('2026-08-20T07:00:00Z'));

    const { result } = renderHook(() => useActiveIncidents());

    expect(result.current.status).toBe('loading');
    expect(result.current.snapshot).toBeUndefined();
    await act(async () => {
      resolveInitial?.(snapshot('2026-08-20T06:00:00Z'));
    });
    await waitFor(() => expect(result.current.status).toBe('success'));
    expect(result.current.snapshot?.retrieved_at).toBe('2026-08-20T06:00:00Z');

    await act(async () => {
      await result.current.refresh();
    });

    expect(fetchActiveIncidents).toHaveBeenCalledTimes(2);
    expect(result.current.snapshot?.retrieved_at).toBe('2026-08-20T07:00:00Z');
  });

  it('reports an initial retrieval failure without fabricating a snapshot', async () => {
    vi.mocked(fetchActiveIncidents).mockRejectedValue(
      new Error('Provider request failed.'),
    );

    const { result } = renderHook(() => useActiveIncidents());

    await waitFor(() => expect(result.current.status).toBe('error'));
    expect(result.current.error).toBe('Provider request failed.');
    expect(result.current.snapshot).toBeUndefined();
  });

  it('falls back to an explicitly stale read-only snapshot', async () => {
    window.localStorage.setItem(
      'disaster-monitor:last-snapshot:v1:recent:all:',
      JSON.stringify(snapshot('2026-08-20T06:00:00Z')),
    );
    vi.mocked(fetchActiveIncidents).mockRejectedValue(new TypeError('offline'));

    const { result } = renderHook(() => useActiveIncidents());

    await waitFor(() => expect(result.current.status).toBe('offline'));
    expect(result.current.snapshot?.availability).toBe('offline-cache');
    expect(result.current.error).toContain('stale');
  });

  it('does not merge a late page into a different query', async () => {
    let resolvePage: ((value: ActiveIncidentsSnapshot) => void) | undefined;
    vi.mocked(fetchActiveIncidents)
      .mockResolvedValueOnce({ ...snapshot('old'), next_cursor: 'next' })
      .mockReturnValueOnce(
        new Promise((resolve) => {
          resolvePage = resolve;
        }),
      )
      .mockResolvedValueOnce(snapshot('new'));
    const { result } = renderHook(() => useActiveIncidents());
    await waitFor(() => expect(result.current.snapshot?.retrieved_at).toBe('old'));
    let pending: Promise<void> | undefined;
    act(() => {
      pending = result.current.loadMore();
      result.current.setView('ongoing');
    });
    await waitFor(() => expect(result.current.snapshot?.retrieved_at).toBe('new'));
    await act(async () => {
      resolvePage?.({
        ...snapshot('late-old-page'),
        incidents: [
          { event_id: 'stale-event' } as ActiveIncidentsSnapshot['incidents'][number],
        ],
      });
      await pending;
    });
    expect(result.current.snapshot?.retrieved_at).toBe('new');
    expect(result.current.snapshot?.incidents).toEqual([]);
  });

  it('retains distinct sources with the same event id across pages', async () => {
    const incident = (sourceId: string) =>
      ({
        event_id: 'shared-event',
        source: { source_id: sourceId },
      }) as ActiveIncidentsSnapshot['incidents'][number];
    vi.mocked(fetchActiveIncidents)
      .mockResolvedValueOnce({
        ...snapshot('first'),
        snapshot_version: 'v1',
        next_cursor: 'page-2',
        incidents: [incident('source-a')],
      })
      .mockResolvedValueOnce({
        ...snapshot('second'),
        snapshot_version: 'v1',
        incidents: [incident('source-b'), incident('source-b')],
      });
    const { result } = renderHook(() => useActiveIncidents());
    await waitFor(() => expect(result.current.snapshot?.retrieved_at).toBe('first'));
    await act(async () => {
      await result.current.loadMore();
    });
    expect(
      result.current.snapshot?.incidents.map((item) => item.source.source_id),
    ).toEqual(['source-a', 'source-b']);
  });
});
