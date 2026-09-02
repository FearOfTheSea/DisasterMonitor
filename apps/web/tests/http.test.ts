import { describe, expect, it } from 'vitest';

import { readJsonResponse } from '@/shared/api/http';

describe('readJsonResponse', () => {
  it('returns the decoded body for successful responses', async () => {
    const response = new Response(JSON.stringify({ status: 'ok' }), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    });

    await expect(readJsonResponse<{ status: string }>(response)).resolves.toEqual({
      status: 'ok',
    });
  });

  it('uses the supplied fallback when an error response is not JSON', async () => {
    const response = new Response('upstream unavailable', { status: 503 });

    await expect(
      readJsonResponse(response, 'Active Incidents request failed with status 503.'),
    ).rejects.toThrow('Active Incidents request failed with status 503.');
  });

  it('preserves a server-provided detail message', async () => {
    const response = new Response(
      JSON.stringify({ detail: 'Trusted operator identity is not configured.' }),
      { status: 503 },
    );

    await expect(readJsonResponse(response)).rejects.toThrow(
      'Trusted operator identity is not configured.',
    );
  });
});
