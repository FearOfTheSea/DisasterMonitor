import { afterEach, expect, it, vi } from 'vitest';
import { fetchIndexedReporting } from '@/features/incidents/api/indexedReportingClient';

const item = {
  observation_id: 'page-one:0',
  provider: 'index',
  observed_at: '2026-10-31T00:00:00Z',
  publisher: 'Daily',
  title: 'An attributed source headline',
  canonical_url: 'https://daily.example/report',
  published_at: null,
  updated_at: null,
  indexed_at: '2026-10-30T00:00:00Z',
  index_excerpt: 'A literal index excerpt.',
  search_wording: null,
};
const page = {
  items: [item],
  query: 'éboulement',
  snapshot: 'snapshot-one',
  next_cursor: null,
};
afterEach(() => vi.unstubAllGlobals());

it('binds Unicode search, scan and continuation while preserving unknown publication', async () => {
  const fetcher = vi.fn().mockResolvedValue(new Response(JSON.stringify(page)));
  vi.stubGlobal('fetch', fetcher);
  const signal = new AbortController().signal;
  expect(
    await fetchIndexedReporting(
      'scan:one',
      ' éboulement ',
      'cursor',
      'snapshot-one',
      signal,
    ),
  ).toEqual(page);
  const url = new URL(fetcher.mock.calls[0][0]);
  expect(url.pathname).toContain('/scan%3Aone/indexed-reporting');
  expect(url.searchParams.get('query')).toBe('éboulement');
  expect(url.searchParams.get('cursor')).toBe('cursor');
  expect(fetcher.mock.calls[0][1].signal).toBe(signal);
});

it.each([
  { ...page, query: 'different' },
  { ...page, snapshot: 'different' },
  { ...page, snapshot: '' },
  { ...page, items: [], next_cursor: 'next' },
  { ...page, next_cursor: 'cursor' },
  { ...page, items: [item, item] },
  { ...page, items: [{ ...item, canonical_url: 'javascript:alert(1)' }] },
  { ...page, items: [{ ...item, observed_at: 'not-a-date' }] },
])('rejects unbound, unsafe or malformed index responses', async (body) => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify(body))));
  await expect(
    fetchIndexedReporting('scan', 'éboulement', 'cursor', 'snapshot-one'),
  ).rejects.toThrow(/invalid indexed reporting/);
});
