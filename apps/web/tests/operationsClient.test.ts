import { afterEach, describe, expect, it, vi } from 'vitest';

import {
  fetchCountryCatalogStatus,
  fetchEvidenceHistory,
  fetchProviderFreshness,
  recordOperatorReview,
  requestCountryCatalogUpdate,
} from '@/features/operations/api/operationsClient';

describe('operationsClient', () => {
  afterEach(() => vi.unstubAllGlobals());

  it('loads bounded operational views and records a review without an identity header', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify([
            {
              source_id: 'nchmf-vietnam-warnings',
              state: 'fresh',
              last_attempt_at: null,
              last_success_at: '2026-08-13T08:00:00Z',
              effective_at: '2026-08-13T08:00:00Z',
              age_seconds: 30,
              expected_freshness_seconds: 3600,
              consecutive_failures: 0,
              latest_error_code: null,
            },
          ]),
          { status: 200, headers: { 'Content-Type': 'application/json' } },
        ),
      )
      .mockResolvedValueOnce(
        new Response('[]', {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        }),
      )
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            action_id: 'operator-action:1',
            operator_id: 'trusted-operator',
            state_version: 'world-state:1',
            decision: 'reviewed',
            reviewed_at: '2026-08-13T08:00:00Z',
            created: true,
          }),
          { status: 201, headers: { 'Content-Type': 'application/json' } },
        ),
      );
    vi.stubGlobal('fetch', fetchMock);

    expect((await fetchProviderFreshness())[0].state).toBe('fresh');
    expect(await fetchEvidenceHistory()).toEqual([]);
    expect(
      (await recordOperatorReview('world-state:1', 'Checked provenance.')).created,
    ).toBe(true);

    const reviewRequest = fetchMock.mock.calls[2];
    expect(reviewRequest[1]?.headers).toEqual({ 'Content-Type': 'application/json' });
    expect(reviewRequest[1]?.headers).not.toHaveProperty('x-disastermonitor-operator');
  });

  it('surfaces the stable server detail for a fail-closed identity boundary', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({ detail: 'Trusted operator identity is not configured.' }),
          {
            status: 503,
            headers: { 'Content-Type': 'application/json' },
          },
        ),
      ),
    );

    await expect(
      recordOperatorReview('world-state:1', 'Attempted review.'),
    ).rejects.toThrow('Trusted operator identity is not configured.');
  });

  it('loads and requests autonomous country catalog updates', async () => {
    const catalog = {
      state: 'unchanged',
      active_version: 'natural-earth-5.1.2.tzdb-2026b.abc123',
      country_count: 242,
      automatic_updates_enabled: true,
      trigger: 'scheduled',
      last_attempt_at: '2026-08-01T00:00:00Z',
      last_success_at: '2026-08-01T00:00:00Z',
      next_scheduled_at: '2026-09-01T00:00:00Z',
      message: 'Catalog is current.',
      failure_code: null,
      sources: [],
    };
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(
        new Response(JSON.stringify(catalog), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        }),
      )
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ ...catalog, state: 'updated' }), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        }),
      );
    vi.stubGlobal('fetch', fetchMock);

    expect((await fetchCountryCatalogStatus()).country_count).toBe(242);
    expect((await requestCountryCatalogUpdate()).state).toBe('updated');
    expect(fetchMock.mock.calls[1]).toEqual([
      expect.stringContaining('/operations/country-catalog/update'),
      { method: 'POST' },
    ]);
  });
});
