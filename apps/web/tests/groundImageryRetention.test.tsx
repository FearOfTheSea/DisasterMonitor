import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import type { GroundImageryRetention } from '@/features/imagery/model/groundImageryRetention';
import { GroundImageryPanel } from '@/features/imagery/ui/GroundImageryPanel';
import { comparisonRequest, readiness, request } from './groundImageryPanelFixtures';
const api = vi.hoisted(() => ({
  createGroundImageryRequest: vi.fn(),
  fetchGroundImageryReadiness: vi.fn(),
  fetchGroundImageryRequest: vi.fn(),
  prepareGroundImagerySelection: vi.fn(),
  replaceGroundImageryRegion: vi.fn(),
  refreshGroundImageryRequest: vi.fn(),
  setGroundImageryWatch: vi.fn(),
  selectGroundImageryObservation: vi.fn(),
}));
vi.mock('@/features/imagery/api/groundImageryClient', () => api);
vi.mock('@/shared/hooks/useMonitoringReadiness', () => ({
  useMonitoringReadiness: () => ({ available: true }),
}));
const retention = {
  read: vi.fn<GroundImageryRetention['read']>(() => ({
    requestId: request.request_id,
    artifactId: 'artifact:before',
  })),
  saveRequest: vi.fn(),
  saveArtifact: vi.fn(),
  clear: vi.fn(),
};
function mount(incidentTime: string | null = '2024-05-19T12:00:00Z') {
  return render(
    <GroundImageryPanel
      {...{ retention }}
      findOnOpen
      incidentId="incident-1"
      incidentLabel="Flood"
      incidentTime={incidentTime}
      onClose={vi.fn()}
    />,
  );
}
beforeEach(() => {
  vi.clearAllMocks();
  vi.stubGlobal(
    'ResizeObserver',
    class {
      observe() {}
      unobserve() {}
      disconnect() {}
    },
  );
  api.fetchGroundImageryReadiness.mockResolvedValue({ ...readiness, state: 'ready' });
  api.createGroundImageryRequest.mockResolvedValue(request);
  api.fetchGroundImageryRequest.mockResolvedValue(comparisonRequest);
  api.prepareGroundImagerySelection.mockResolvedValue(comparisonRequest);
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});
it('restores a prepared request and capture after remount without creating or preparing', async () => {
  const view = mount();
  await screen.findByText('Region basis');
  expect(api.fetchGroundImageryRequest).toHaveBeenCalledWith(
    request.request_id,
    expect.any(AbortSignal),
  );
  expect(api.createGroundImageryRequest).not.toHaveBeenCalled();
  expect(api.prepareGroundImagerySelection).not.toHaveBeenCalled();
  expect(screen.getByRole('combobox', { name: 'Prepared capture' })).toHaveValue(
    'artifact:before',
  );
  view.unmount();
  mount();
  await screen.findByRole('combobox', { name: 'Prepared capture' });
  expect(api.fetchGroundImageryRequest).toHaveBeenCalledTimes(2);
  expect(api.createGroundImageryRequest).not.toHaveBeenCalled();
});
it('rejects a retained request belonging to another event without silently creating one', async () => {
  api.fetchGroundImageryRequest.mockResolvedValue({
    ...comparisonRequest,
    incident_id: 'incident-2',
  });
  mount();
  await waitFor(() =>
    expect(screen.getByRole('alert')).toHaveTextContent('different event'),
  );
  expect(screen.queryByText('Region basis')).not.toBeInTheDocument();
  expect(api.createGroundImageryRequest).not.toHaveBeenCalled();
});
it('keeps failed restoration explicit and does not start a new catalog search', async () => {
  api.fetchGroundImageryRequest.mockRejectedValue(
    new Error('Saved request not found.'),
  );
  mount();
  expect(await screen.findByRole('alert')).toHaveTextContent(
    'Saved request not found.',
  );
  expect(
    screen.getByRole('button', { name: 'Start a new imagery search' }),
  ).toBeVisible();
  expect(api.createGroundImageryRequest).not.toHaveBeenCalled();
});
it('can inspect retained imagery when current event time is unresolved', async () => {
  mount(null);
  expect(await screen.findByRole('combobox', { name: 'Prepared capture' })).toHaveValue(
    'artifact:before',
  );
  expect(api.createGroundImageryRequest).not.toHaveBeenCalled();
  expect(api.prepareGroundImagerySelection).not.toHaveBeenCalled();
});

it('remembers a new request and a changed capture for subsequent reloads', async () => {
  retention.read.mockReturnValueOnce(undefined);
  api.createGroundImageryRequest.mockResolvedValue(comparisonRequest);
  mount();
  await screen.findByRole('combobox', { name: 'Prepared capture' });
  expect(retention.saveRequest).toHaveBeenCalledWith('incident-1', request.request_id);
  fireEvent.change(screen.getByRole('combobox', { name: 'Prepared capture' }), {
    target: { value: 'artifact:before' },
  });
  expect(retention.saveArtifact).toHaveBeenCalledWith(
    'incident-1',
    request.request_id,
    'artifact:before',
  );
});
it('starts fresh only after the user explicitly replaces a failed saved request', async () => {
  api.fetchGroundImageryRequest.mockRejectedValue(
    new Error('Saved request not found.'),
  );
  mount();
  await screen.findByRole('alert');
  expect(api.createGroundImageryRequest).not.toHaveBeenCalled();
  retention.clear.mockImplementationOnce(() =>
    retention.read.mockReturnValueOnce(undefined),
  );
  fireEvent.click(screen.getByRole('button', { name: 'Start a new imagery search' }));
  await screen.findByText('Region basis');
  expect(retention.clear).toHaveBeenCalledWith('incident-1');
  expect(api.createGroundImageryRequest).toHaveBeenCalledOnce();
});
