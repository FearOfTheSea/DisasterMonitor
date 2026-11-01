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

it('loads complete claims before presenting a summary with an existing map position', async () => {
  const local = {
    event_id: 'discovery:summary',
    reporting_detail: 'on_selection',
    provider_ids: [],
    geometry: { kind: 'point', coordinates: [] },
    discovery_reports: [{ capture_id: 'capture-one', claims: [] }],
  } as unknown as ActiveIncident;
  let finish!: (value: ActiveIncident) => void;
  vi.mocked(fetchActiveIncident).mockImplementation(
    () =>
      new Promise((resolve) => {
        finish = resolve;
      }),
  );
  const { result } = renderHook(() => useIncidentSelection(local.event_id, [local]));
  expect(result.current.incident).toBeUndefined();
  expect(result.current.loading).toBe(true);
  const complete = {
    ...local,
    reporting_detail: 'full',
    discovery_reports: [{ capture_id: 'capture-one', claims: [{ value: '3' }] }],
  } as unknown as ActiveIncident;
  finish(complete);
  await waitFor(() => expect(result.current.incident).toBe(complete));
  expect(result.current.loading).toBe(false);
});

it('shows a lookup failure without turning deferred claims into unknown impacts', async () => {
  const local = {
    event_id: 'discovery:summary',
    reporting_detail: 'on_selection',
    provider_ids: [],
  } as unknown as ActiveIncident;
  vi.mocked(fetchActiveIncident).mockRejectedValue(
    new Error('Retained details unavailable'),
  );
  const { result } = renderHook(() => useIncidentSelection(local.event_id, [local]));
  await waitFor(() =>
    expect(result.current.error).toBe('Retained details unavailable'),
  );
  expect(result.current.incident).toBeUndefined();
  expect(result.current.loading).toBe(false);
});

it('reloads changed capture details without rendering the previous source version', async () => {
  const local = {
    event_id: 'discovery:summary',
    reporting_detail: 'on_selection',
    provider_ids: [],
    discovery_reports: [{ capture_id: 'capture-one' }],
  } as unknown as ActiveIncident;
  const complete = { ...local, reporting_detail: 'full' } as ActiveIncident;
  vi.mocked(fetchActiveIncident).mockResolvedValueOnce(complete);
  const { result, rerender } = renderHook(
    ({ record }) => useIncidentSelection(local.event_id, [record]),
    { initialProps: { record: local } },
  );
  await waitFor(() => expect(result.current.incident).toBe(complete));
  rerender({ record: { ...local } });
  expect(fetchActiveIncident).toHaveBeenCalledTimes(1);
  let finish!: (value: ActiveIncident) => void;
  vi.mocked(fetchActiveIncident).mockImplementationOnce(
    () =>
      new Promise((resolve) => {
        finish = resolve;
      }),
  );
  const updated = {
    ...local,
    discovery_reports: [{ capture_id: 'capture-two' }],
  } as unknown as ActiveIncident;
  rerender({ record: updated });
  expect(result.current.incident).toBeUndefined();
  expect(result.current.loading).toBe(true);
  const next = { ...updated, reporting_detail: 'full' } as ActiveIncident;
  finish(next);
  await waitFor(() => expect(result.current.incident).toBe(next));
});

it('resolves summary geometry only for the same captures and keeps its source metadata', async () => {
  const local = {
    event_id: 'discovery:summary',
    reporting_detail: 'on_selection',
    provider_ids: [],
    event_time: null,
    geometry: null,
    source: { canonical_url: 'https://news.example/report' },
    discovery_reports: [
      { capture_id: 'capture-one', mention_id: 'mention-one', claims: [] },
    ],
  } as unknown as ActiveIncident;
  const complete = {
    ...local,
    reporting_detail: 'full',
    geometry: { kind: 'point', coordinates: [] },
    discovery_reports: [
      {
        capture_id: 'capture-one',
        mention_id: 'mention-one',
        claims: [{ value: '3' }],
      },
    ],
  } as unknown as ActiveIncident;
  vi.mocked(fetchActiveIncident).mockResolvedValue(complete);
  const { result } = renderHook(() => useIncidentSelection(local.event_id, [local]));
  await waitFor(() => expect(result.current.incident).toBe(complete));
  expect(result.current.withResolvedLocation(local).geometry).toBe(complete.geometry);
  expect(result.current.withResolvedLocation(local).discovery_reports).toBe(
    local.discovery_reports,
  );
  const updated = {
    ...local,
    discovery_reports: [{ capture_id: 'capture-two', mention_id: 'mention-one' }],
  } as unknown as ActiveIncident;
  expect(result.current.withResolvedLocation(updated).geometry).toBeNull();
});
