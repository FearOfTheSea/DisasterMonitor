import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { fetchSourceCatalog } from '@/features/sources/api/sourceCatalogClient';
import { SourceCatalog } from '@/features/sources/ui/SourceCatalog';

vi.mock('@/features/sources/api/sourceCatalogClient', () => ({
  fetchSourceCatalog: vi.fn(),
}));

describe('SourceCatalog', () => {
  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
    window.localStorage.clear();
  });

  it('reports the loading error when an offline source record is malformed', async () => {
    window.localStorage.setItem(
      'disaster-monitor:pwa:source-catalog:v1',
      JSON.stringify({
        schemaVersion: 1,
        cachedAt: '2026-10-07T00:00:00Z',
        value: { catalog_version: '2.8.0', sources: [{ source_id: 'broken' }] },
      }),
    );
    vi.mocked(fetchSourceCatalog).mockRejectedValue(new Error('Network unavailable.'));

    render(<SourceCatalog onClose={vi.fn()} />);

    expect(await screen.findByRole('alert')).toHaveTextContent('Network unavailable.');
    expect(screen.queryByText(/stale source catalog cached/)).not.toBeInTheDocument();
  });

  it('is read-only and explains metadata separately from runtime state', async () => {
    vi.mocked(fetchSourceCatalog).mockResolvedValue({
      catalog_version: '2.8.0',
      sources: [
        {
          source_id: 'nws-weather-alerts',
          provider: 'NWS active weather alerts',
          publisher: 'NOAA/National Weather Service',
          authority: 'national_authority',
          information_roles: ['official_warning'],
          supported_disasters: [],
          geographic_scopes: ['country'],
          country_codes: ['USA'],
          coverage_description: 'United States land areas',
          documentation_path: 'docs/sources/noaa-nws-weather-alerts.md',
          freshness_semantics: 'Active pull feed',
          stale_threshold_seconds: null,
          attribution: 'NOAA/NWS',
          limitations: ['Not global.'],
          operational_state: {
            registered: true,
            configured: true,
            availability: 'available',
            availability_detail: 'Registered; health checked on request.',
            provider_tier: 'primary',
            execution_roles: ['weather_alerts'],
          },
          rights_id: 'noaa-nws-public-domain',
          access_model: 'public',
          license_name: 'U.S. Government work / NWS terms',
          rights_reviewed_at: '2026-09-13',
        },
      ],
    });

    render(<SourceCatalog onClose={vi.fn()} />);

    await waitFor(() =>
      expect(screen.getByText('NWS active weather alerts')).toBeVisible(),
    );
    expect(screen.getByText('NOAA/National Weather Service')).toBeVisible();
    expect(
      screen.getByText(/official warning.*United States land areas/i),
    ).toBeVisible();
    await userEvent
      .setup()
      .click(screen.getByRole('button', { name: 'View provenance and limitations' }));
    expect(screen.getByText(/No physical disaster type/i)).toBeVisible();
    expect(screen.getByText(/Stale threshold: unspecified/i)).toBeVisible();
    expect(screen.getByText(/public.*noaa-nws-public-domain/i)).toBeVisible();
    expect(screen.getByText(/Registered; health checked on request/i)).toBeVisible();
    expect(screen.queryByRole('checkbox')).not.toBeInTheDocument();
    expect(screen.queryByRole('switch')).not.toBeInTheDocument();

    vi.mocked(fetchSourceCatalog).mockRejectedValue(new Error('Network unavailable.'));
    await userEvent
      .setup()
      .click(screen.getByRole('button', { name: 'Refresh metadata' }));
    expect(await screen.findByText(/stale source catalog cached/)).toBeVisible();
    expect(screen.getByText('NWS active weather alerts')).toBeVisible();
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });
});
