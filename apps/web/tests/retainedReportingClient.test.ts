import { afterEach, expect, it, vi } from 'vitest';
import { fetchRetainedReporting } from '@/features/incidents/api/retainedReportingClient';

afterEach(() => vi.unstubAllGlobals());
const source = {
  source_id: 'news',
  publisher: 'Daily',
  title: 'Regional wildfires',
  canonical_url: 'https://daily.example/report',
  retrieved_at: '2026-10-26T12:00:00Z',
};
const page = {
  capture_id: 'capture-one',
  source,
  bylines: ['Author'],
  origin: null,
  original_url: null,
  text: 'Quote 😀',
  offset: 0,
  total_characters: 7,
  next_offset: null,
  unavailable_reason: null,
};

it('fetches only the requested retained capture and preserves Unicode offsets', async () => {
  const fetcher = vi.fn().mockResolvedValue(new Response(JSON.stringify(page)));
  vi.stubGlobal('fetch', fetcher);
  const signal = new AbortController().signal;
  expect(
    await fetchRetainedReporting('discovery:scan:event', 'capture-one', 0, signal),
  ).toEqual(page);
  expect(fetcher.mock.calls[0][0]).toContain(
    '/incidents/discovery%3Ascan%3Aevent/reporting/capture-one?offset=0',
  );
  expect(fetcher.mock.calls[0][1].signal).toBe(signal);
});

it.each([
  {},
  { ...page, capture_id: 'different-capture' },
  { ...page, offset: 1 },
  { ...page, next_offset: 0 },
  { ...page, next_offset: 8, total_characters: 10 },
  { ...page, total_characters: 9 },
])('rejects an invalid or mismatched retained page', async (value) => {
  vi.stubGlobal(
    'fetch',
    vi.fn().mockResolvedValue(new Response(JSON.stringify(value))),
  );
  await expect(fetchRetainedReporting('event', 'capture-one', 0)).rejects.toThrow(
    'invalid retained source',
  );
});

it('preserves a real unavailable response and transport failures', async () => {
  vi.stubGlobal(
    'fetch',
    vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          ...page,
          text: '',
          total_characters: 0,
          unavailable_reason: 'No readable text retained.',
        }),
      ),
    ),
  );
  expect(
    (await fetchRetainedReporting('event', 'capture-one', 0)).unavailable_reason,
  ).toBe('No readable text retained.');
  vi.stubGlobal(
    'fetch',
    vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ detail: 'Capture not retained.' }), {
        status: 404,
      }),
    ),
  );
  await expect(fetchRetainedReporting('event', 'capture-one', 0)).rejects.toThrow(
    'Capture not retained.',
  );
});
