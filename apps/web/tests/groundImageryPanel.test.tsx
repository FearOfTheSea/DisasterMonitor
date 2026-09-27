import { act, cleanup, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { GroundImageryPanel } from '@/features/imagery/ui/GroundImageryPanel';
import type {
  GroundImageryReadinessResponse,
  GroundImageryRequestResponse,
} from '@/shared/api/generated/assistant';

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

const request: GroundImageryRequestResponse = {
  request_id: 'ground-imagery:1',
  request_version: 1,
  incident_id: 'incident-1',
  disaster: 'flood',
  state: 'partial',
  reason_codes: ['no_recent_observation'],
  reference_time: '2024-05-20T00:00:00Z',
  region: {
    state: 'resolved',
    region: {
      region_id: 'region:1',
      version: 1,
      geometry_hash: 'hash',
      association: 'confirmed',
      core: { type: 'MultiPolygon', coordinates: [] },
      inspection: { type: 'MultiPolygon', coordinates: [] },
      source_footprints: [{ source_kind: 'mapped_impact' }],
    },
    alternatives: [],
    warnings: [
      'The reported-place boundary lookup was unavailable.',
      'The region is a point-derived inspection buffer.',
    ],
    reason_code: null,
  },
  temporal_plan: {
    policy_version: 'sentinel-ground-view-v1',
    reference_time: '2024-05-20T00:00:00Z',
    impact_start_earliest: null,
    impact_start_latest: null,
    onset_precision: null,
    onset_source_id: null,
    windows: [],
  },
  sensors: [
    {
      sensor: 'sentinel-1',
      scanned_count: 3,
      scan_complete: true,
      next_cursor: null,
      failure_code: null,
      failure_detail: null,
      selections: [
        {
          selection_id: 'selection:s1',
          sensor: 'sentinel-1',
          role: 'latest_useful',
          label: 'Latest useful view',
          observation: null,
          reason: 'no_recent_observation',
          explanation: 'No recent radar capture was found.',
          age_class: null,
          alternative_observation_ids: [],
        },
      ],
    },
    {
      sensor: 'sentinel-2',
      scanned_count: 0,
      scan_complete: true,
      next_cursor: null,
      failure_code: null,
      failure_detail: null,
      selections: [],
    },
  ],
  next_check_at: null,
  watch_enabled: false,
  watch_interval_seconds: null,
  artifacts: [],
};

const readiness: GroundImageryReadinessResponse = {
  state: 'credentials_required',
  detail: 'Catalog discovery is available.',
};

const observation = (productId: string, capturedStart: string) => ({
  observation_id: `observation:${productId}`,
  sensor: 'sentinel-1' as const,
  product_id: productId,
  acquisition_id: productId,
  revision: null,
  platform: 'Sentinel-1A',
  captured_start: capturedStart,
  captured_end: capturedStart,
  readiness: 'downloaded',
  footprint: { type: 'MultiPolygon', coordinates: [] },
  mode: 'IW',
  relative_orbit: 12,
  orbit_direction: 'ascending',
  polarizations: ['VV'],
  cloud_cover_fraction: null,
  quality: null,
  source_url: 'https://catalogue.dataspace.copernicus.eu/product',
});

const grid = {
  crs: 'EPSG:4326',
  min_x: 105,
  min_y: 20,
  max_x: 106,
  max_y: 21,
  pixel_size_m: 10,
  width: 512,
  height: 512,
  resolution_label: '10 m',
};

const comparisonRequest: GroundImageryRequestResponse = {
  ...request,
  region: {
    ...request.region,
    region: {
      ...request.region.region!,
      inspection: {
        type: 'MultiPolygon',
        coordinates: [
          [
            [
              [105, 20],
              [106, 20],
              [106, 21],
              [105, 20],
            ],
          ],
        ],
      },
    },
  },
  sensors: [
    {
      ...request.sensors[0],
      selections: [
        {
          selection_id: 'selection:before',
          sensor: 'sentinel-1',
          role: 'pre_event_reference',
          label: 'Pre-event reference',
          observation: observation('S1-before', '2024-05-10T00:00:00Z'),
          reason: 'selected',
          explanation: 'Selected before capture.',
          age_class: 'recent',
          alternative_observation_ids: [],
        },
        {
          selection_id: 'selection:after',
          sensor: 'sentinel-1',
          role: 'first_useful_after_onset',
          label: 'First useful after onset',
          observation: observation('S1-after', '2024-05-21T00:00:00Z'),
          reason: 'selected',
          explanation: 'Selected after capture.',
          age_class: 'recent',
          alternative_observation_ids: [],
        },
      ],
    },
    request.sensors[1],
  ],
  artifacts: [
    {
      artifact_id: 'artifact:before',
      selection_id: 'selection:before',
      sensor: 'sentinel-1',
      role: 'pre_event_reference',
      output_kind: 'overview',
      content_type: 'image/tiff; application=geotiff',
      storage_key: 'before.tif',
      byte_count: 100,
      sha256: 'a'.repeat(64),
      source_product_ids: ['S1-before'],
      grid,
      created_at: '2024-05-21T01:00:00Z',
    },
    {
      artifact_id: 'artifact:after',
      selection_id: 'selection:after',
      sensor: 'sentinel-1',
      role: 'first_useful_after_onset',
      output_kind: 'overview',
      content_type: 'image/tiff; application=geotiff',
      storage_key: 'after.tif',
      byte_count: 100,
      sha256: 'b'.repeat(64),
      source_product_ids: ['S1-after'],
      grid,
      created_at: '2024-05-21T01:00:00Z',
    },
  ],
};

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
