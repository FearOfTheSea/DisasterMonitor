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

it('adds source-supported geography on selection without replacing retained reporting', async () => {
  const local = {
    event_id: 'discovery:event',
    physical_event_id: 'discovery:event',
    provider_ids: [],
    geometry: null,
    location: 'Example District',
    event_time: '2026-08-26T00:00:00Z',
    source: { canonical_url: 'https://news.example/report' },
    measurements: [],
  } as unknown as ActiveIncident;
  const geometry = {
    kind: 'area',
    estimated: true,
    coordinates: [],
  } as unknown as NonNullable<IncidentMapRecord['geometry']>;
  vi.mocked(fetchActiveIncident).mockResolvedValue({ ...local, geometry });
  const { result, rerender } = renderHook(
    ({ selected }: { selected?: string }) => useIncidentSelection(selected, [local]),
    { initialProps: { selected: local.event_id as string | undefined } },
  );
  await waitFor(() => expect(result.current.incident?.geometry).toBe(geometry));
  expect(result.current.incident?.source).toBe(local.source);
  expect(local.geometry).toBeNull();
  rerender({ selected: undefined });
  expect(result.current.incident).toBeUndefined();
  expect(result.current.withResolvedLocation(local).geometry).toBe(geometry);
  expect(
    result.current.withResolvedLocation({
      ...local,
      event_time: '2026-08-27T00:00:00Z',
    }).geometry,
  ).toBeNull();
});
