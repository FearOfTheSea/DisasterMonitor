import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterAll, afterEach, beforeAll, expect, it, vi } from 'vitest';
import { IndexedReporting } from '@/features/incidents/ui/IndexedReporting';

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
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});
const item = {
  observation_id: 'page:0',
  provider: 'bing-rss-discovery',
  observed_at: '2026-10-31T00:00:00Z',
  publisher: 'Local Daily',
  title: 'Slide killed two near the village',
  canonical_url: 'https://daily.example/story',
  published_at: null,
  updated_at: null,
  indexed_at: '2026-10-30T00:00:00Z',
  index_excerpt: 'Literal <script>index wording</script>',
  search_wording: null,
};
const props = {
  scanId: 'scan',
  intervalStart: '2026-10-24T00:00:00Z',
  intervalEnd: '2026-10-31T00:00:00Z',
};

it('exposes index-only wording, continuation and provenance without inventing publication', async () => {
  const fetcher = vi
    .fn()
    .mockResolvedValueOnce(
      new Response(
        JSON.stringify({
          items: [item],
          query: '',
          snapshot: 'same',
          next_cursor: 'next',
        }),
      ),
    )
    .mockResolvedValueOnce(
      new Response(
        JSON.stringify({
          items: [
            { ...item, observation_id: 'page:1', published_at: '2026-10-01T00:00:00Z' },
          ],
          query: '',
          snapshot: 'same',
          next_cursor: null,
        }),
      ),
    )
    .mockResolvedValueOnce(
      new Response(
        JSON.stringify({
          items: [],
          query: 'unmatched',
          snapshot: 'new',
          next_cursor: null,
        }),
      ),
    );
  vi.stubGlobal('fetch', fetcher);
  render(<IndexedReporting {...props} />);
  expect(fetcher).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole('button', { name: 'Inspect indexed reporting' }));
  await screen.findByText('Index excerpt: Literal <script>index wording</script>');
  expect(
    screen.getByText(
      /Publication time unknown; reporting-window eligibility is unresolved/,
    ),
  ).toBeInTheDocument();
  expect(document.querySelector('script')).toBeNull();
  fireEvent.click(screen.getByText('Index provenance and wording'));
  expect(screen.getByText(/Bing News/)).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Load more index entries' }));
  await screen.findByText('Publication outside this scan’s reporting window.');
  expect(new URL(fetcher.mock.calls[1][0]).searchParams.get('cursor')).toBe('next');
  expect(screen.getAllByRole('link', { name: /Local Daily:/ })).toHaveLength(2);
  fireEvent.change(
    screen.getByRole('searchbox', { name: 'Search indexed reporting' }),
    { target: { value: 'unmatched' } },
  );
  fireEvent.click(screen.getByRole('button', { name: 'Search index entries' }));
  await screen.findByText('No matching index observations in this scan.');
  expect(new URL(fetcher.mock.calls[2][0]).searchParams.has('cursor')).toBe(false);
  fireEvent.click(screen.getByRole('button', { name: 'Close indexed reporting' }));
  await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
});

it('aborts a closed search and can reopen without waiting for its old response', async () => {
  const fetcher = vi
    .fn()
    .mockImplementationOnce(() => new Promise(() => {}))
    .mockResolvedValueOnce(
      new Response(
        JSON.stringify({
          items: [item],
          query: '',
          snapshot: 'same',
          next_cursor: null,
        }),
      ),
    );
  vi.stubGlobal('fetch', fetcher);
  render(<IndexedReporting {...props} />);
  fireEvent.click(screen.getByRole('button', { name: 'Inspect indexed reporting' }));
  fireEvent.click(screen.getByRole('button', { name: 'Close indexed reporting' }));
  expect(fetcher.mock.calls[0][1].signal.aborted).toBe(true);
  fireEvent.click(screen.getByRole('button', { name: 'Inspect indexed reporting' }));
  await screen.findByText('Index excerpt: Literal <script>index wording</script>');
});
