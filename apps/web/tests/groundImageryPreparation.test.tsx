import { act, cleanup, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { GroundImageryPanel } from '@/features/imagery/ui/GroundImageryPanel';

import {
  comparisonRequest,
  observation,
  readiness,
  request,
} from './groundImageryPanelFixtures';

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

describe('Ground imagery preparation and comparison', () => {
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

  it('keeps a prepared capture visible after a refresh changes the selection', async () => {
    api.createGroundImageryRequest.mockResolvedValue({
      ...request,
      request_version: 2,
      artifacts: [
        {
          ...comparisonRequest.artifacts![1],
          observation: observation('S1-after', '2024-05-21T00:00:00Z'),
        },
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

    expect(await screen.findByText('Prepared observation')).toBeVisible();
    expect(screen.getByAltText('Sentinel-1 radar after capture')).toBeVisible();
  });

  it('previews a usable radar capture ahead of a newer obscured optical capture', async () => {
    api.createGroundImageryRequest.mockResolvedValue({
      ...request,
      artifacts: [
        {
          ...comparisonRequest.artifacts![1],
          selection_id: 'radar-prepared',
          observation: {
            ...observation('S1-clear', '2024-05-22T00:00:00Z'),
            quality: {
              covered_fraction: 1,
              usable_fraction: 1,
              obscured_fraction: 0,
              uncertain_fraction: 0,
              uncovered_fraction: 0,
              component_usable_fractions: { 'component-1': 1 },
              quality_state: 'useful',
              mask_definition: 's1-core-datamask-v1',
            },
          },
        },
        {
          ...comparisonRequest.artifacts![1],
          artifact_id: 'artifact:clouded',
          selection_id: 'optical-prepared',
          sensor: 'sentinel-2',
          observation: {
            ...observation('S2-clouded', '2024-05-23T00:00:00Z'),
            sensor: 'sentinel-2',
            quality: {
              covered_fraction: 1,
              usable_fraction: 0,
              obscured_fraction: 1,
              uncertain_fraction: 0,
              uncovered_fraction: 0,
              component_usable_fractions: { 'component-1': 0 },
              quality_state: 'obscured',
              mask_definition: 's2-core-scl-datamask-v1',
            },
          },
        },
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

    expect(await screen.findByAltText('Sentinel-1 radar after capture')).toBeVisible();
    expect(screen.queryByAltText('Sentinel-2 optical after capture')).toBeNull();
  });

  it('shows matched-grid side-by-side and swipe comparison controls', async () => {
    const user = userEvent.setup();
    api.createGroundImageryRequest.mockResolvedValue(comparisonRequest);
    render(
      <GroundImageryPanel
        incidentId="incident-1"
        incidentLabel="River basin"
        incidentTime="2024-05-19T12:00:00Z"
        onClose={vi.fn()}
      />,
    );

    expect(await screen.findByText('Matched before / after')).toBeVisible();
    expect(screen.getByAltText('Sentinel-1 radar before capture')).toBeVisible();
    expect(screen.getByText(/S1-before → S1-after/)).toBeVisible();
    expect(
      screen.getByText(/no comparison manifest or export has been generated/i),
    ).toBeVisible();
    await user.click(screen.getByRole('button', { name: 'Swipe' }));
    expect(screen.getByRole('slider', { name: 'Reveal position' })).toBeVisible();
  });

  it('shows a prepared post-event image even before a comparison pair exists', async () => {
    api.createGroundImageryRequest.mockResolvedValue({
      ...comparisonRequest,
      artifacts: [comparisonRequest.artifacts![1]],
    });
    render(
      <GroundImageryPanel
        incidentId="incident-1"
        incidentLabel="River basin"
        incidentTime="2024-05-19T12:00:00Z"
        onClose={vi.fn()}
      />,
    );

    expect(await screen.findByText('Prepared observation')).toBeVisible();
    expect(screen.getByAltText('Sentinel-1 radar after capture')).toBeVisible();
    expect(screen.getByText(/does not establish damage or safety/i)).toBeVisible();
    expect(
      screen.getByRole('region', { name: 'Observation coverage map' }),
    ).toBeVisible();
    expect(screen.getByText(/Transparent pixels have no data/)).toBeVisible();
    expect(screen.getByText(/Search window as of/)).toBeVisible();
    expect(screen.getAllByText(/Sensed through/)).toHaveLength(2);
  });

  it('prepares one selected post-event capture automatically when rendering is ready', async () => {
    api.createGroundImageryRequest.mockResolvedValue({
      ...comparisonRequest,
      artifacts: [],
    });
    api.fetchGroundImageryReadiness.mockResolvedValue({
      state: 'ready',
      detail: 'Authenticated rendering is available.',
    });
    api.prepareGroundImagerySelection.mockResolvedValue({
      ...comparisonRequest,
      artifacts: [comparisonRequest.artifacts![1]],
    });
    render(
      <GroundImageryPanel
        incidentId="incident-1"
        incidentLabel="River basin"
        incidentTime="2024-05-19T12:00:00Z"
        onClose={vi.fn()}
      />,
    );

    expect(await screen.findByText('Prepared observation')).toBeVisible();
    expect(api.prepareGroundImagerySelection).toHaveBeenCalledTimes(1);
    expect(api.prepareGroundImagerySelection).toHaveBeenCalledWith('ground-imagery:1', {
      sensor: 'sentinel-1',
      role: 'first_useful_after_onset',
      overview: true,
    });
  });

  it('prepares a newer useful capture even when an older artifact exists', async () => {
    const latest = {
      ...comparisonRequest.sensors[0].selections[1],
      selection_id: 'selection:latest',
      role: 'latest_useful',
      observation: observation('S1-latest', '2024-05-23T00:00:00Z'),
    };
    api.createGroundImageryRequest.mockResolvedValue({
      ...comparisonRequest,
      sensors: [
        {
          ...comparisonRequest.sensors[0],
          selections: [...comparisonRequest.sensors[0].selections, latest],
        },
        comparisonRequest.sensors[1],
      ],
      artifacts: [comparisonRequest.artifacts![1]],
    });
    api.fetchGroundImageryReadiness.mockResolvedValue({
      state: 'ready',
      detail: 'Authenticated rendering is available.',
    });
    api.prepareGroundImagerySelection.mockResolvedValue(comparisonRequest);
    render(
      <GroundImageryPanel
        incidentId="incident-1"
        incidentLabel="River basin"
        incidentTime="2024-05-19T12:00:00Z"
        onClose={vi.fn()}
      />,
    );

    await screen.findByText('Latest useful view');
    expect(api.prepareGroundImagerySelection).toHaveBeenCalledWith('ground-imagery:1', {
      sensor: 'sentinel-1',
      role: 'latest_useful',
      overview: true,
    });
  });

  it('refreshes a queued preparation until its image is available', async () => {
    vi.useFakeTimers();
    api.createGroundImageryRequest.mockResolvedValue({
      ...comparisonRequest,
      state: 'queued',
      artifacts: [],
    });
    api.fetchGroundImageryRequest.mockResolvedValue({
      ...comparisonRequest,
      state: 'ready',
      artifacts: [comparisonRequest.artifacts![1]],
    });
    render(
      <GroundImageryPanel
        incidentId="incident-1"
        incidentLabel="River basin"
        incidentTime="2024-05-19T12:00:00Z"
        onClose={vi.fn()}
      />,
    );

    await act(async () => vi.advanceTimersByTimeAsync(0));
    await act(async () => vi.advanceTimersByTimeAsync(3_000));

    expect(api.fetchGroundImageryRequest).toHaveBeenCalledWith(
      'ground-imagery:1',
      expect.any(AbortSignal),
    );
    expect(screen.getByText('Prepared observation')).toBeVisible();
  });

  it('polls a watched request after preparation is complete', async () => {
    vi.useFakeTimers();
    api.createGroundImageryRequest.mockResolvedValue({
      ...comparisonRequest,
      watch_enabled: true,
      next_check_at: '2024-05-21T01:00:00Z',
    });
    api.fetchGroundImageryRequest.mockResolvedValue({
      ...comparisonRequest,
      request_version: 2,
      watch_enabled: true,
    });
    render(
      <GroundImageryPanel
        incidentId="incident-1"
        incidentLabel="River basin"
        incidentTime="2024-05-19T12:00:00Z"
        onClose={vi.fn()}
      />,
    );

    await act(async () => vi.advanceTimersByTimeAsync(0));
    await act(async () => vi.advanceTimersByTimeAsync(30_000));

    expect(api.fetchGroundImageryRequest).toHaveBeenCalledWith(
      'ground-imagery:1',
      expect.any(AbortSignal),
    );
    expect(screen.getByText(/Request ground-imagery:1 · version 2/)).toBeVisible();
  });
});
