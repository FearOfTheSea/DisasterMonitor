import { afterEach, describe, expect, it, vi } from 'vitest';

import {
  createGroundImageryRequest,
  fetchGroundImageryReadiness,
  replaceGroundImageryRegion,
  setGroundImageryWatch,
} from '@/features/imagery/api/groundImageryClient';

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

  it('lets the server timestamp searches and choose the watch cadence', async () => {
    const response = { request_id: 'unused' };
    const fetchMock = vi
      .spyOn(globalThis, 'fetch')
      .mockImplementation(
        async () => new Response(JSON.stringify(response), { status: 202 }),
      );
    await expect(createGroundImageryRequest('incident-1')).rejects.toThrow(
      'invalid response',
    );
    expect(JSON.parse(String(fetchMock.mock.calls[0][1]?.body))).toEqual({
      incident_id: 'incident-1',
      idempotency_key: 'ground-view:incident-1',
      refresh_if_stale: true,
    });

    await expect(setGroundImageryWatch('request-1', true)).rejects.toThrow(
      'invalid response',
    );
    expect(JSON.parse(String(fetchMock.mock.calls[1][1]?.body))).toEqual({
      enabled: true,
      interval_seconds: null,
    });
  });

  it('sends a selected inspection area to the versioned region endpoint', async () => {
    const fetchMock = vi
      .spyOn(globalThis, 'fetch')
      .mockResolvedValue(new Response(JSON.stringify({}), { status: 202 }));
    const region = {
      type: 'MultiPolygon',
      coordinates: [
        [
          [
            [136.9, 35.1],
            [137, 35.1],
            [136.9, 35.1],
          ],
        ],
      ],
    };

    await expect(replaceGroundImageryRegion('request-1', region)).rejects.toThrow(
      'invalid response',
    );
    expect(fetchMock).toHaveBeenCalledWith(
      'http://localhost:8001/api/v1/ground-imagery/requests/request-1/regions',
      expect.objectContaining({ method: 'POST' }),
    );
    expect(JSON.parse(String(fetchMock.mock.calls[0][1]?.body))).toEqual({ region });
  });
});
