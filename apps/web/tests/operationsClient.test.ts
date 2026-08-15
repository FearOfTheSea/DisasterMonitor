import { afterEach, describe, expect, it, vi } from 'vitest';

import {
  fetchEvidenceHistory,
  fetchProviderFreshness,
  recordOperatorReview,
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
});
