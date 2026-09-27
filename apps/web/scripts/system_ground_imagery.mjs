import { readFile } from 'node:fs/promises';

export async function exerciseGroundImagery(page) {
  const groundObservation = {
    observation_id: 'fixture-s2-capture',
    sensor: 'sentinel-2',
    product_id: 'S2-FIXTURE-20260926',
    acquisition_id: 'S2-FIXTURE-20260926',
    revision: null,
    platform: 'Sentinel-2A',
    captured_start: '2026-09-26T02:00:00Z',
    captured_end: '2026-09-26T02:05:00Z',
    readiness: 'downloaded',
    footprint: {
      type: 'MultiPolygon',
      coordinates: [
        [
          [
            [104.5, 14.5],
            [105.5, 14.5],
            [105.5, 15.5],
            [104.5, 15.5],
            [104.5, 14.5],
          ],
        ],
      ],
    },
    mode: null,
    relative_orbit: null,
    orbit_direction: null,
    polarizations: [],
    cloud_cover_fraction: 0.15,
    quality: {
      covered_fraction: 0.9,
      usable_fraction: 0.7,
      obscured_fraction: 0.2,
      uncertain_fraction: 0,
      uncovered_fraction: 0.1,
      component_usable_fractions: { 'component-1': 0.7 },
      quality_state: 'partial',
      mask_definition: 's2-core-scl-datamask-v1',
    },
    source_url: null,
  };
  const groundRequest = {
    request_id: 'ground-imagery:system-fixture',
    request_version: 2,
    incident_id: 'system-flood',
    disaster: 'flood',
    state: 'ready',
    reason_codes: ['partial_coverage'],
    reference_time: '2026-09-27T12:00:00Z',
    region: {
      state: 'resolved',
      reason_code: null,
      warnings: [],
      alternatives: [],
      region: {
        region_id: 'region:system-fixture',
        version: 1,
        geometry_hash: 'fixture',
        association: 'user_selected',
        core: {
          type: 'MultiPolygon',
          coordinates: [
            [
              [
                [104.9, 14.9],
                [105.1, 14.9],
                [105.1, 15.1],
                [104.9, 15.1],
                [104.9, 14.9],
              ],
            ],
          ],
        },
        inspection: {
          type: 'MultiPolygon',
          coordinates: [
            [
              [
                [104.7, 14.7],
                [105.3, 14.7],
                [105.3, 15.3],
                [104.7, 15.3],
                [104.7, 14.7],
              ],
            ],
          ],
        },
        source_footprints: [{ source_kind: 'user_selected' }],
      },
    },
    temporal_plan: {
      policy_version: 'sentinel-ground-view-v1',
      reference_time: '2026-09-27T12:00:00Z',
      impact_start_earliest: null,
      impact_start_latest: null,
      onset_precision: null,
      onset_source_id: null,
      windows: [],
    },
    sensors: [
      {
        sensor: 'sentinel-1',
        scanned_count: 0,
        scan_complete: true,
        next_cursor: null,
        failure_code: null,
        failure_detail: null,
        selections: [],
      },
      {
        sensor: 'sentinel-2',
        scanned_count: 1,
        scan_complete: true,
        next_cursor: null,
        failure_code: null,
        failure_detail: null,
        selections: [
          {
            selection_id: 'selection:system-fixture',
            sensor: 'sentinel-2',
            role: 'latest_useful',
            label: 'Latest useful view',
            observation: groundObservation,
            reason: 'partial_coverage',
            explanation: 'Rendered core assessment: 70% usable.',
            age_class: 'recent',
            alternative_observation_ids: [],
          },
        ],
      },
    ],
    watch_enabled: true,
    watch_interval_seconds: 3600,
    next_check_at: '2026-09-27T13:00:00Z',
    artifacts: [
      {
        artifact_id: 'artifact:system-fixture',
        selection_id: 'selection:system-fixture',
        sensor: 'sentinel-2',
        role: 'latest_useful',
        output_kind: 's2-natural-color',
        content_type: 'image/tiff',
        storage_key: 'system-fixture.tif',
        byte_count: 100,
        sha256: 'a'.repeat(64),
        source_product_ids: ['S2-FIXTURE-20260926'],
        grid: {
          crs: 'EPSG:32648',
          min_x: 0,
          min_y: 0,
          max_x: 5120,
          max_y: 5120,
          pixel_size_m: 10,
          width: 512,
          height: 512,
          resolution_label: '10 m',
        },
        created_at: '2026-09-27T12:00:00Z',
        observation: groundObservation,
      },
    ],
    jobs: [],
  };
  const fixturePng = await readFile(
    new URL('./fixtures/ground_tile.png', import.meta.url),
  );
  let activeGroundRequest = {
    ...groundRequest,
    request_version: 1,
    state: 'needs_region',
    region: {
      state: 'needs_region',
      reason_code: 'needs_region',
      warnings: ['The source point is a broad event locator.'],
      alternatives: [],
      region: null,
    },
    sensors: [],
    artifacts: [],
  };
  await page.route('**/api/v1/ground-imagery/**', async (route) => {
    const url = route.request().url();
    if (url.endsWith('/readiness')) {
      return route.fulfill({
        json: {
          state: 'credentials_required',
          detail: 'Catalog available; processing credentials are absent.',
        },
      });
    }
    if (url.endsWith('.png')) {
      return route.fulfill({
        body: fixturePng,
        contentType: 'image/png',
        headers: { 'Access-Control-Allow-Origin': '*' },
      });
    }
    if (url.endsWith('/regions') && route.request().method() === 'POST') {
      const { region } = route.request().postDataJSON();
      if (region.type !== 'MultiPolygon' || region.coordinates[0][0].length !== 65)
        throw new Error('The selected inspection circle was not submitted.');
      activeGroundRequest = groundRequest;
    }
    return route.fulfill({ json: activeGroundRequest });
  });
  await page.getByRole('button', { name: 'Explore', exact: true }).click();
  const groundTileResponse = page.waitForResponse((response) =>
    response
      .url()
      .includes('/ground-imagery/artifacts/artifact%3Asystem-fixture/tiles/'),
  );
  await page.getByRole('button', { name: 'Focus Thailand on map' }).click();
  await page.getByRole('heading', { name: 'Ground view' }).waitFor();
  await page.getByText('The source point is a broad event locator.').waitFor();
  await page.getByLabel('Center latitude').fill('15');
  await page.getByLabel('Center longitude').fill('105');
  await page.getByRole('button', { name: 'Search this area' }).click();
  await page.getByRole('heading', { name: 'Prepared observation' }).waitFor();
  await page.getByText('user selected', { exact: true }).waitFor();
  await page.getByRole('region', { name: 'Observation coverage map' }).waitFor();
  await page.getByText('Core usable 70% · covered 90%').waitFor();
  await page.getByLabel('Image opacity 85%').fill('50');
  await page.getByText('Image opacity 50%').waitFor();
  if (!(await groundTileResponse).ok()) {
    throw new Error('The Ground coverage map did not load its stored image tile.');
  }
  await page.waitForFunction(() => {
    const canvas = document.querySelector('.ground-coverage-map-canvas canvas');
    const context = canvas?.getContext('2d');
    if (!context) return false;
    const [red, green, blue, alpha] = context.getImageData(
      canvas.width / 2,
      canvas.height / 2,
      1,
      1,
    ).data;
    return alpha > 100 && red > green + 20 && red > blue + 20;
  });
  if (process.env.SYSTEM_TEST_GROUND_SCREENSHOT) {
    await page.screenshot({
      path: process.env.SYSTEM_TEST_GROUND_SCREENSHOT,
      fullPage: false,
    });
  }
}
