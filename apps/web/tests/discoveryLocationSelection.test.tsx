import { cleanup, renderHook, waitFor } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { fetchActiveIncident } from '@/features/incidents/api/incidentsClient';
import {
  matchesIncidentIdentifier,
  useIncidentSelection,
} from '@/features/incidents/hooks/useIncidentSelection';
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

it('restores an old scan link using its scoped record for lookup and imagery', async () => {
  const legacy = 'discovery:record';
  const local = {
    event_id: `discovery:11111111-1111-4111-8111-111111111111:${legacy}`,
    provider_ids: [],
    geometry: null,
    event_time: '2026-10-14T00:00:00Z',
    source: { canonical_url: 'https://news.example/report' },
  } as unknown as ActiveIncident;
  vi.mocked(fetchActiveIncident).mockResolvedValue(local);
  const { result } = renderHook(() => useIncidentSelection(legacy, [local]));
  await waitFor(() =>
    expect(fetchActiveIncident).toHaveBeenCalledWith(
      local.event_id,
      expect.any(AbortSignal),
    ),
  );
  expect(result.current.incident?.event_id).toBe(local.event_id);
  expect(matchesIncidentIdentifier(local, legacy)).toBe(true);
  expect(
    matchesIncidentIdentifier(
      local,
      'discovery:22222222-2222-4222-8222-222222222222:discovery:record',
    ),
  ).toBe(false);
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
