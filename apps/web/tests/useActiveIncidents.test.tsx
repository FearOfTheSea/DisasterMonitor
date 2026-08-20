import { act, renderHook, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

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
  beforeEach(() => vi.clearAllMocks());

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
});
