import { afterEach, describe, expect, it, vi } from 'vitest';

import { fetchSourceCatalog } from '@/features/sources/api/sourceCatalogClient';

describe('sourceCatalogClient', () => {
  afterEach(() => vi.restoreAllMocks());

  it('loads the bounded read model without provider controls', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(
        JSON.stringify({
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
        }),
        { status: 200, headers: { 'Content-Type': 'application/json' } },
      ),
    );

    const result = await fetchSourceCatalog();

    expect(result.sources[0].operational_state.execution_roles).toEqual([
      'weather_alerts',
    ]);
    expect(JSON.stringify(result)).not.toContain('allowed_hosts');
    expect(JSON.stringify(result)).not.toContain('enabled');
  });

  it('rejects malformed operational state', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(JSON.stringify({ catalog_version: 'x', sources: [{}] }), {
        status: 200,
      }),
    );
    await expect(fetchSourceCatalog()).rejects.toThrow(/invalid response/i);
  });
});
