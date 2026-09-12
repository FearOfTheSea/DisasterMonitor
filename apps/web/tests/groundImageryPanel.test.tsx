import { cleanup, render, screen } from '@testing-library/react';
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
  prepareGroundImagerySelection: vi.fn(),
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
    warnings: [],
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

describe('GroundImageryPanel', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    api.createGroundImageryRequest.mockResolvedValue(request);
    api.fetchGroundImageryReadiness.mockResolvedValue(readiness);
    api.refreshGroundImageryRequest.mockResolvedValue(request);
    api.setGroundImageryWatch.mockResolvedValue({
      ...request,
      watch_enabled: true,
      next_check_at: '2024-05-20T06:00:00Z',
    });
  });

  afterEach(cleanup);

  it('shows the region, temporal uncertainty, and independent sensor states', async () => {
    render(
      <GroundImageryPanel
        incidentId="incident-1"
        incidentLabel="River basin"
        onClose={vi.fn()}
      />,
    );

    expect(await screen.findByText('Credentials required')).toBeVisible();
    expect(screen.getByRole('heading', { name: 'Ground view' })).toBeVisible();
    expect(screen.getByText('River basin')).toBeVisible();
    expect(screen.getByText('Credentials required')).toBeVisible();
    expect(screen.getByText('Sentinel-1 radar')).toBeVisible();
    expect(screen.getByText('Sentinel-2 optical')).toBeVisible();
    expect(screen.getByText('Onset unknown')).toBeVisible();
    expect(screen.getByText('No recent observation')).toBeVisible();
  });

  it('refreshes the request and persists a watch action', async () => {
    const user = userEvent.setup();
    render(
      <GroundImageryPanel
        incidentId="incident-1"
        incidentLabel="River basin"
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
