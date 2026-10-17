import { cleanup, renderHook, waitFor } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { fetchActiveIncident } from '@/features/incidents/api/incidentsClient';
import { useIncidentSelection } from '@/features/incidents/hooks/useIncidentSelection';
import type {
  ActiveIncident,
  IncidentMapRecord,
} from '@/features/incidents/model/activeIncidents';

vi.mock('@/features/incidents/api/incidentsClient', () => ({
  fetchActiveIncident: vi.fn(),
}));
afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

it('resolves a provider alias even when no loaded page contains the event', async () => {
  const incident = {
    event_id: 'new-provider:1',
    physical_event_id: 'physical:1',
    provider_ids: ['old-provider:1', 'new-provider:1'],
  } as ActiveIncident;
  vi.mocked(fetchActiveIncident).mockResolvedValue(incident);
  const { result, rerender } = renderHook(
    ({ records }) => useIncidentSelection('old-provider:1', records),
    { initialProps: { records: [] as IncidentMapRecord[] } },
  );
  await waitFor(() => expect(result.current.incident).toBe(incident));
  rerender({
    records: [
      {
        ...incident,
        event_id: 'unrelated',
        physical_event_id: 'physical:2',
        provider_ids: [],
      },
    ],
  });
  expect(result.current.incident).toBe(incident);
});

it('explains an ambiguous link without selecting a candidate', async () => {
  vi.mocked(fetchActiveIncident).mockRejectedValue(
    new Error('Incident identifier is ambiguous.'),
  );
  const { result } = renderHook(() => useIncidentSelection('old-physical:1', []));
  await waitFor(() => expect(result.current.error).toContain('ambiguous'));
  expect(result.current.incident).toBeUndefined();
});
