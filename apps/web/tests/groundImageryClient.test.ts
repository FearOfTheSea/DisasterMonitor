import { afterEach, describe, expect, it, vi } from 'vitest';

import { fetchGroundImageryReadiness } from '@/features/imagery/api/groundImageryClient';

describe('ground imagery client', () => {
  afterEach(() => vi.restoreAllMocks());

  it('validates the readiness response against the generated contract', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(
        JSON.stringify({
          state: 'credentials_required',
          detail: 'Configure CDSE credentials.',
        }),
        { status: 200, headers: { 'Content-Type': 'application/json' } },
      ),
    );

    await expect(fetchGroundImageryReadiness()).resolves.toEqual({
      state: 'credentials_required',
      detail: 'Configure CDSE credentials.',
    });
    expect(fetchMock).toHaveBeenCalledWith(
      'http://localhost:8001/api/v1/ground-imagery/readiness',
      { signal: undefined },
    );
  });

  it('rejects a successful response that violates the contract', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(JSON.stringify({ state: 'ready' }), { status: 200 }),
    );

    await expect(fetchGroundImageryReadiness()).rejects.toThrow('invalid response');
  });
});
