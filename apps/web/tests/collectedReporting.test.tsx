import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from '@testing-library/react';
import { afterAll, afterEach, beforeAll, expect, it, vi } from 'vitest';
import { DiscoveryScanControls } from '@/features/incidents/ui/DiscoveryScanControls';
import type { DiscoveryScanResponse } from '@/shared/api/generated/assistant';

const originalShow = Object.getOwnPropertyDescriptor(
  HTMLDialogElement.prototype,
  'showModal',
);
const originalClose = Object.getOwnPropertyDescriptor(
  HTMLDialogElement.prototype,
  'close',
);
beforeAll(() => {
  Object.defineProperty(HTMLDialogElement.prototype, 'showModal', {
    configurable: true,
    value() {
      this.setAttribute('open', '');
    },
  });
  Object.defineProperty(HTMLDialogElement.prototype, 'close', {
    configurable: true,
    value() {
      this.removeAttribute('open');
    },
  });
});
afterAll(() => {
  if (originalShow)
    Object.defineProperty(HTMLDialogElement.prototype, 'showModal', originalShow);
  else Reflect.deleteProperty(HTMLDialogElement.prototype, 'showModal');
  if (originalClose)
    Object.defineProperty(HTMLDialogElement.prototype, 'close', originalClose);
  else Reflect.deleteProperty(HTMLDialogElement.prototype, 'close');
});

const capture = 'b'.repeat(64);
const source = {
  source_id: 'news',
  publisher: 'Local Daily',
  title: 'Road construction account',
  canonical_url: 'https://daily.example/road',
  published_at: null,
  retrieved_at: '2026-10-27T06:00:00Z',
  publication_precision: 'unknown',
};
const item = {
  capture_id: capture,
  source,
  bylines: ['A. Reporter'],
  origin: 'wire:shared',
  original_url: null,
  disaster: null,
  eligibility: 'unknown_publication',
  event_linked: false,
  access_issue: null,
  text_preview: 'A worker died during road work.',
};
const run = {
  scan_id: 'retained-scan',
  status: 'incomplete',
  reports_seen: 1,
  interval_start: '2026-10-20T06:00:00Z',
  interval_end: '2026-10-27T06:00:00Z',
  issues: [],
  unlocated_count: 0,
  snapshot: { incidents: [] },
} as unknown as DiscoveryScanResponse;

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

it('opens unclassified collected evidence without requiring a hazard event', async () => {
  const text = 'A worker died when material fell. <script>literal quote</script> 😀';
  const fetcher = vi
    .fn()
    .mockResolvedValueOnce(
      new Response(
        JSON.stringify({
          items: [item],
          version: 'a'.repeat(64),
          offset: 0,
          total: 1,
          next_offset: null,
          unlinked_only: true,
        }),
      ),
    )
    .mockResolvedValueOnce(
      new Response(
        JSON.stringify({
          capture_id: capture,
          source,
          bylines: ['A. Reporter'],
          origin: 'wire:shared',
          original_url: null,
          text,
          offset: 0,
          total_characters: Array.from(text).length,
          next_offset: null,
          unavailable_reason: null,
        }),
      ),
    );
  vi.stubGlobal('fetch', fetcher);
  const { container } = render(
    <DiscoveryScanControls
      days={7}
      onDaysChange={vi.fn()}
      onScan={vi.fn()}
      run={run}
    />,
  );
  expect(fetcher).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole('button', { name: 'Inspect collected reporting' }));
  const entry = await screen.findByRole('article', {
    name: 'Road construction account',
  });
  expect(within(entry).getByText(/Publication unknown/)).toBeVisible();
  expect(within(entry).getByText(/Unclassified/)).toBeVisible();
  expect(within(entry).getByText(/A\. Reporter/)).toBeVisible();
  fireEvent.click(
    within(entry).getByRole('button', { name: 'Read retained source text' }),
  );
  await waitFor(() => expect(within(entry).getByText(text)).toBeVisible());
  expect(container.querySelector('script')).toBeNull();
  expect(fetcher.mock.calls[1][0]).toContain(
    `/discovery-scans/retained-scan/reporting/${capture}`,
  );
});

it('continues the report catalog without losing earlier rows', async () => {
  const entries = Array.from({ length: 26 }, (_, index) => ({
    ...item,
    capture_id: index.toString(16).padStart(64, '0'),
    source: { ...source, title: `Account ${index}` },
  }));
  const fetcher = vi
    .fn()
    .mockResolvedValueOnce(
      new Response(
        JSON.stringify({
          items: entries.slice(0, 25),
          version: 'a'.repeat(64),
          offset: 0,
          total: 26,
          next_offset: 25,
          unlinked_only: true,
        }),
      ),
    )
    .mockResolvedValueOnce(
      new Response(
        JSON.stringify({
          items: entries.slice(25),
          version: 'a'.repeat(64),
          offset: 25,
          total: 26,
          next_offset: null,
          unlinked_only: true,
        }),
      ),
    );
  vi.stubGlobal('fetch', fetcher);
  render(
    <DiscoveryScanControls
      days={7}
      onDaysChange={vi.fn()}
      onScan={vi.fn()}
      run={run}
    />,
  );
  fireEvent.click(screen.getByRole('button', { name: 'Inspect collected reporting' }));
  await screen.findByRole('article', { name: 'Account 0' });
  fireEvent.click(screen.getByRole('button', { name: 'Show more collected reports' }));
  await screen.findByRole('article', { name: 'Account 25' });
  expect(screen.getAllByRole('article')).toHaveLength(26);
  expect(screen.getByText('26 of 26 reports loaded.')).toBeVisible();
  expect(fetcher.mock.calls[1][0]).toContain(
    `offset=25&unlinked_only=true&version=${'a'.repeat(64)}`,
  );
});

it('keeps loaded reporting visible after a changed-catalog response and allows reload', async () => {
  const response = {
    items: [item],
    version: 'a'.repeat(64),
    offset: 0,
    total: 2,
    next_offset: 1,
    unlinked_only: true,
  };
  const fetcher = vi
    .fn()
    .mockResolvedValueOnce(new Response(JSON.stringify(response)))
    .mockResolvedValueOnce(
      new Response(
        JSON.stringify({ detail: 'Collected reporting changed. Reload the reports.' }),
        { status: 409 },
      ),
    )
    .mockResolvedValueOnce(
      new Response(
        JSON.stringify({
          ...response,
          version: 'c'.repeat(64),
          total: 1,
          next_offset: null,
        }),
      ),
    );
  vi.stubGlobal('fetch', fetcher);
  render(
    <DiscoveryScanControls
      days={7}
      onDaysChange={vi.fn()}
      onScan={vi.fn()}
      run={run}
    />,
  );
  fireEvent.click(screen.getByRole('button', { name: 'Inspect collected reporting' }));
  await screen.findByRole('article', { name: 'Road construction account' });
  fireEvent.click(screen.getByRole('button', { name: 'Show more collected reports' }));
  expect(await screen.findByRole('alert')).toHaveTextContent(
    'Collected reporting changed',
  );
  expect(
    screen.getByRole('article', { name: 'Road construction account' }),
  ).toBeVisible();
  fireEvent.click(screen.getByRole('button', { name: 'Reload collected reports' }));
  await screen.findByText('1 of 1 reports loaded.');
  expect(screen.queryByRole('alert')).toBeNull();
});
