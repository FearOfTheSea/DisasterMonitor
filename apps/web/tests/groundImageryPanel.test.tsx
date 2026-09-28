import { act, cleanup, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { GroundImageryPanel } from '@/features/imagery/ui/GroundImageryPanel';
import type {
  GroundImageryReadinessResponse,
  GroundImageryRequestResponse,
} from '@/shared/api/generated/assistant';

import { observation, readiness, request } from './groundImageryPanelFixtures';

const api = vi.hoisted(() => ({
  createGroundImageryRequest: vi.fn(),
  fetchGroundImageryReadiness: vi.fn(),
  fetchGroundImageryRequest: vi.fn(),
  prepareGroundImagerySelection: vi.fn(),
  replaceGroundImageryRegion: vi.fn(),
  refreshGroundImageryRequest: vi.fn(),
  setGroundImageryWatch: vi.fn(),
}));

vi.mock('@/features/imagery/api/groundImageryClient', () => api);

describe('GroundImageryPanel', () => {
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
    api.createGroundImageryRequest.mockResolvedValue(request);
    api.fetchGroundImageryReadiness.mockResolvedValue(readiness);
    api.refreshGroundImageryRequest.mockResolvedValue(request);
    api.setGroundImageryWatch.mockResolvedValue({
      ...request,
      watch_enabled: true,
      next_check_at: '2024-05-20T06:00:00Z',
    });
  });

  afterEach(() => {
    cleanup();
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it('shows readiness and slow-provider guidance while catalog search continues', async () => {
    vi.useFakeTimers();
    api.createGroundImageryRequest.mockImplementation(
      () => new Promise<GroundImageryRequestResponse>(() => undefined),
    );

    render(
      <GroundImageryPanel
        incidentId="incident-1"
        incidentLabel="River basin"
        incidentTime="2024-05-19T12:00:00Z"
        onClose={vi.fn()}
      />,
    );

    await act(async () => vi.advanceTimersByTimeAsync(0));

    expect(screen.getByText('Catalog discovery is available.')).toBeVisible();
    expect(screen.getByText('Searching Sentinel acquisitions')).toBeVisible();

    await act(async () => vi.advanceTimersByTimeAsync(8_000));

    expect(
      screen.getByText(/Copernicus Data Space is taking longer than usual/),
    ).toBeVisible();
  });

  it('shows the region, temporal uncertainty, and independent sensor states', async () => {
    const { container } = render(
      <GroundImageryPanel
        incidentId="incident-1"
        incidentLabel="Flood · River basin"
        incidentTime="2024-05-19T12:00:00Z"
        onClose={vi.fn()}
      />,
    );

    expect(await screen.findByText('Credentials required')).toBeVisible();
    expect(screen.getByRole('heading', { name: 'Ground view' })).toBeVisible();
    expect(screen.getByText('Flood · River basin')).toBeVisible();
    expect(
      container.querySelector('time[datetime="2024-05-19T12:00:00Z"]'),
    ).toBeVisible();
    expect(screen.getByText('Credentials required')).toBeVisible();
    expect(screen.getByText('Onset unknown')).toBeVisible();
    expect(screen.getByText('No recent observation')).toBeVisible();
    const stage = screen.getByRole('region', { name: 'Ground comparisons' });
    expect(within(stage).getByText('Sentinel-1 radar')).toBeVisible();
    expect(within(stage).getByText('No recent radar capture was found.')).toBeVisible();
    expect(within(stage).getByText('Sentinel-2 optical')).toBeVisible();
    expect(within(stage).getByText('No role result returned.')).toBeVisible();
    expect(
      screen.getByText('The reported-place boundary lookup was unavailable.'),
    ).toBeVisible();
    expect(
      screen.getByText('The region is a point-derived inspection buffer.'),
    ).toBeVisible();
  });

  it('does not call an obscured capture useful after the raster is assessed', async () => {
    api.createGroundImageryRequest.mockResolvedValue({
      ...request,
      sensors: [
        {
          ...request.sensors[0],
          selections: [
            {
              ...request.sensors[0].selections[0],
              role: 'latest_useful',
              observation: observation('S1-clouded', '2024-05-21T00:00:00Z'),
              reason: 'obscured',
            },
          ],
        },
        request.sensors[1],
      ],
    });
    render(
      <GroundImageryPanel
        incidentId="incident-1"
        incidentLabel="River basin"
        incidentTime="2024-05-19T12:00:00Z"
        onClose={vi.fn()}
      />,
    );

    expect(await screen.findByText('Latest capture')).toBeVisible();
    expect(screen.queryByText('Latest useful view')).not.toBeInTheDocument();
    expect(screen.getByText('Obscured or uncertain')).toBeVisible();
  });

  it('lets an operator search a selected area when event geometry is insufficient', async () => {
    const user = userEvent.setup();
    api.createGroundImageryRequest.mockResolvedValue({
      ...request,
      state: 'needs_region',
      region: {
        state: 'needs_region',
        region: null,
        alternatives: [],
        warnings: ['The event point is only a locator.'],
        reason_code: 'needs_region',
      },
    });
    api.replaceGroundImageryRegion.mockResolvedValue({
      ...request,
      request_version: 2,
    });
    render(
      <GroundImageryPanel
        incidentId="incident-1"
        incidentLabel="Flood · broad region"
        incidentTime="2024-05-19T12:00:00Z"
        onClose={vi.fn()}
      />,
    );

    expect(await screen.findByText('The event point is only a locator.')).toBeVisible();
    await user.type(screen.getByLabelText('Center latitude'), '35.1');
    await user.type(screen.getByLabelText('Center longitude'), '136.9');
    await user.click(screen.getByRole('button', { name: 'Search this area' }));

    expect(api.replaceGroundImageryRegion).toHaveBeenCalledOnce();
    const [requestId, region] = api.replaceGroundImageryRegion.mock.calls[0];
    expect(requestId).toBe('ground-imagery:1');
    expect(region.type).toBe('MultiPolygon');
    expect(region.coordinates[0][0]).toHaveLength(65);
    const longitudes = region.coordinates[0][0].map((point: number[]) => point[0]);
    const latitudes = region.coordinates[0][0].map((point: number[]) => point[1]);
    expect(Math.min(...longitudes)).toBeGreaterThan(136);
    expect(Math.max(...longitudes)).toBeLessThan(138);
    expect(Math.min(...latitudes)).toBeGreaterThan(34);
    expect(Math.max(...latitudes)).toBeLessThan(36);
    expect(screen.getByText('Request ground-imagery:1 · version 2')).toBeVisible();
  });

  it('rejects an inspection circle that crosses the unsupported date line', async () => {
    const user = userEvent.setup();
    api.createGroundImageryRequest.mockResolvedValue({
      ...request,
      state: 'needs_region',
      region: { ...request.region, state: 'needs_region', region: null },
    });
    render(
      <GroundImageryPanel
        incidentId="incident-1"
        incidentLabel="Coastal flood"
        incidentTime="2024-05-19T12:00:00Z"
        onClose={vi.fn()}
      />,
    );

    await user.type(await screen.findByLabelText('Center latitude'), '35');
    await user.type(screen.getByLabelText('Center longitude'), '179.99');
    await user.selectOptions(screen.getByLabelText('Radius'), '30');
    await user.click(screen.getByRole('button', { name: 'Search this area' }));

    expect(screen.getByRole('alert')).toHaveTextContent('date line');
    expect(api.replaceGroundImageryRegion).not.toHaveBeenCalled();
  });

  it('clears the previous incident while the next ground view loads', async () => {
    const { rerender } = render(
      <GroundImageryPanel
        incidentId="incident-1"
        incidentLabel="River basin"
        incidentTime="2024-05-19T12:00:00Z"
        onClose={vi.fn()}
      />,
    );

    expect(await screen.findByText('Region basis')).toBeVisible();

    api.createGroundImageryRequest.mockImplementation(
      () => new Promise<GroundImageryRequestResponse>(() => undefined),
    );
    api.fetchGroundImageryReadiness.mockImplementation(
      () => new Promise<GroundImageryReadinessResponse>(() => undefined),
    );
    rerender(
      <GroundImageryPanel
        incidentId="incident-2"
        incidentLabel="Coastal earthquake"
        incidentTime="2024-05-19T12:00:00Z"
        onClose={vi.fn()}
      />,
    );

    expect(await screen.findByText('Searching Sentinel acquisitions')).toBeVisible();
    expect(screen.getByText('Coastal earthquake')).toBeVisible();
    expect(screen.queryByText('Region basis')).not.toBeInTheDocument();
    expect(screen.queryByText('Request ground-imagery:1')).not.toBeInTheDocument();
  });

  it('refreshes the request and persists a watch action', async () => {
    const user = userEvent.setup();
    render(
      <GroundImageryPanel
        incidentId="incident-1"
        incidentLabel="River basin"
        incidentTime="2024-05-19T12:00:00Z"
        onClose={vi.fn()}
      />,
    );
    await screen.findByText('Refresh catalog');

    await user.click(screen.getByRole('button', { name: 'Refresh catalog' }));
    await user.click(screen.getByRole('button', { name: 'Watch for new captures' }));

    expect(api.refreshGroundImageryRequest).toHaveBeenCalledWith('ground-imagery:1');
    expect(api.setGroundImageryWatch).toHaveBeenCalledWith('ground-imagery:1', true);
  });
});
