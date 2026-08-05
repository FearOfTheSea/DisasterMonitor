import { afterEach, describe, expect, it, vi } from 'vitest';

import {
  AssistantApiError,
  AssistantClient,
} from '@/features/assistant/api/assistantClient';

describe('AssistantClient', () => {
  afterEach(() => vi.restoreAllMocks());

  it('posts the typed question and current map view', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(
        JSON.stringify({
          message: 'Use the map to inspect the area.',
          conversation_id: 'session-1',
          model: 'fake-qwen',
        }),
        { status: 200, headers: { 'Content-Type': 'application/json' } },
      ),
    );
    const client = new AssistantClient('http://localhost:8001/api/v1');

    await expect(
      client.ask('What is visible?', null, {
        centerLatitude: 21.03,
        centerLongitude: 105.85,
        zoom: 10,
      }),
    ).resolves.toMatchObject({ model: 'fake-qwen' });
    expect(fetchMock).toHaveBeenCalledWith(
      'http://localhost:8001/api/v1/assistant',
      expect.objectContaining({
        method: 'POST',
        body: expect.stringContaining('center_latitude'),
      }),
    );
  });

  it('translates an API error into a stable client error', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(JSON.stringify({ detail: 'The local model is unavailable.' }), {
        status: 503,
        headers: { 'Content-Type': 'application/json' },
      }),
    );
    const client = new AssistantClient('http://localhost:8001/api/v1');

    await expect(
      client.ask('Will it flood?', null, {
        centerLatitude: 21,
        centerLongitude: 105,
        zoom: 8,
      }),
    ).rejects.toEqual(
      expect.objectContaining<Partial<AssistantApiError>>({ status: 503 }),
    );
  });

  it('accepts structured current-disaster metadata and source timestamps', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(
        JSON.stringify({
          message: '## Situation summary',
          conversation_id: 'session-1',
          model: 'source-backed-report',
          response_type: 'current_disaster',
          retrieval_time: '2026-08-05T12:00:00Z',
          sources: [
            {
              publisher: 'JMA',
              title: 'Fixture event',
              canonical_url: 'https://example.test/event',
              published_at: '2026-08-05T11:00:00Z',
              retrieved_at: '2026-08-05T12:00:00Z',
            },
          ],
          sections: [{ title: 'Situation summary', content: 'Verified.' }],
          warnings: ['One source is unavailable.'],
          partial: true,
        }),
        { status: 200, headers: { 'Content-Type': 'application/json' } },
      ),
    );
    const client = new AssistantClient('http://localhost:8001/api/v1');

    await expect(
      client.ask('Latest earthquake damage?', null, {
        centerLatitude: 21,
        centerLongitude: 105,
        zoom: 8,
      }),
    ).resolves.toMatchObject({ response_type: 'current_disaster', partial: true });
  });
});
