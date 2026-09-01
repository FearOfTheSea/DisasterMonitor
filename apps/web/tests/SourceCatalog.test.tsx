import { render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { fetchSourceCatalog } from '@/features/sources/api/sourceCatalogClient';
import { SourceCatalog } from '@/features/sources/ui/SourceCatalog';

vi.mock('@/features/sources/api/sourceCatalogClient', () => ({
  fetchSourceCatalog: vi.fn(),
}));

describe('SourceCatalog', () => {
  afterEach(() => vi.clearAllMocks());

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
        },
      ],
    });

    render(<SourceCatalog onClose={vi.fn()} />);

    await waitFor(() =>
      expect(screen.getByText('NWS active weather alerts')).toBeVisible(),
    );
    expect(screen.getByText('NOAA/National Weather Service')).toBeVisible();
    expect(screen.getByText(/official warning/i)).toBeVisible();
    expect(screen.getByText(/No physical disaster type/i)).toBeVisible();
    expect(screen.getByText(/Stale threshold: unspecified/i)).toBeVisible();
    expect(screen.getByText(/Registered; health checked on request/i)).toBeVisible();
    expect(screen.queryByRole('checkbox')).not.toBeInTheDocument();
    expect(screen.queryByRole('switch')).not.toBeInTheDocument();
  });
});
