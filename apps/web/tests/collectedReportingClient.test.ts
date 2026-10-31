import { afterEach, expect, it, vi } from 'vitest';
import { fetchCollectedReporting } from '@/features/incidents/api/collectedReportingClient';

const item = {
  capture_id: 'b'.repeat(64),
  source: {
    source_id: 'news',
    publisher: 'Daily',
    title: 'Retained account',
    canonical_url: 'https://daily.example/report',
    retrieved_at: '2026-10-27T06:00:00Z',
  },
  bylines: [],
  origin: null,
  original_url: null,
  disaster: null,
  eligibility: 'unclassified',
  event_linked: false,
  access_issue: null,
  text_preview: 'Retained text',
};
const page = {
  items: [item],
  version: 'a'.repeat(64),
  offset: 0,
  total: 1,
  next_offset: null,
  unlinked_only: true,
};
afterEach(() => vi.unstubAllGlobals());

it('binds the catalog request to its scan and selection', async () => {
  const fetcher = vi.fn().mockResolvedValue(new Response(JSON.stringify(page)));
  vi.stubGlobal('fetch', fetcher);
  const signal = new AbortController().signal;
  expect(await fetchCollectedReporting('scan:one', 0, null, true, signal)).toEqual(
    page,
  );
  expect(fetcher.mock.calls[0][0]).toContain(
    '/discovery-scans/scan%3Aone/reporting?offset=0&unlinked_only=true',
  );
  expect(fetcher.mock.calls[0][1].signal).toBe(signal);
});

it.each([
  { ...page, offset: 1 },
  { ...page, unlinked_only: false },
  { ...page, version: 'unversioned' },
  { ...page, items: [], next_offset: 1 },
  { ...page, total: 3, next_offset: 2 },
  { ...page, total: 2, items: [item, item] },
  { ...page, items: [{ ...item, eligibility: 'invented' }] },
])('rejects malformed or unbound continuation', async (body) => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify(body))));
  await expect(fetchCollectedReporting('scan', 0, null, true)).rejects.toThrow(
    /invalid collected reporting/,
  );
});
