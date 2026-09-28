import type {
  GroundImageryReadinessResponse,
  GroundImageryRequestResponse,
} from '@/shared/api/generated/assistant';

export const request: GroundImageryRequestResponse = {
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

export const readiness: GroundImageryReadinessResponse = {
  state: 'credentials_required',
  detail: 'Catalog discovery is available.',
};

export const observation = (productId: string, capturedStart: string) => ({
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

export const comparisonRequest: GroundImageryRequestResponse = {
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
