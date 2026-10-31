import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { RetainedSourceText } from '@/features/incidents/ui/RetainedSourceText';
import { fetchRetainedReporting } from '@/features/incidents/api/retainedReportingClient';

vi.mock('@/features/incidents/api/retainedReportingClient', () => ({
  fetchRetainedReporting: vi.fn(),
}));
afterEach(() => {
  cleanup();
  vi.resetAllMocks();
});
const page = {
  capture_id: 'one',
  source: {
    source_id: 'news',
    publisher: 'Daily',
    title: 'Regional wildfires',
    canonical_url: 'https://daily.example/report',
    retrieved_at: '2026-10-26T12:00:00Z',
  },
  bylines: ['Author'],
  origin: null,
  original_url: null,
  text: 'Regional account. ',
  offset: 0,
  total_characters: 72,
  next_offset: 18,
  unavailable_reason: null,
};

it('loads on demand, continues source passages and keeps them separate from claims', async () => {
  vi.mocked(fetchRetainedReporting)
    .mockResolvedValueOnce(page)
    .mockResolvedValueOnce({
      ...page,
      text: 'A fire in Hilltown killed one person. <script>x</script>',
      offset: 18,
      next_offset: null,
    });
  render(<RetainedSourceText incidentId="event" captureId="one" />);
  expect(fetchRetainedReporting).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole('button', { name: 'Read retained source text' }));
  expect(await screen.findByText('Regional account.')).toBeVisible();
  expect(screen.getByText(/may describe other places or occurrences/)).toBeVisible();
  fireEvent.click(screen.getByRole('button', { name: 'Read more source text' }));
  expect(
    await screen.findByText(
      'Regional account. A fire in Hilltown killed one person. <script>x</script>',
    ),
  ).toBeVisible();
  expect(document.querySelector('script')).toBeNull();
  expect(screen.queryByRole('button', { name: 'Read more source text' })).toBeNull();
  fireEvent.click(screen.getByRole('button', { name: 'Hide retained source text' }));
  fireEvent.click(screen.getByRole('button', { name: 'Read retained source text' }));
  expect(fetchRetainedReporting).toHaveBeenCalledTimes(2);
});

it('keeps earlier text during a continuation failure and retries the same offset', async () => {
  vi.mocked(fetchRetainedReporting)
    .mockResolvedValueOnce(page)
    .mockRejectedValueOnce(new Error('Unavailable now.'))
    .mockResolvedValueOnce({
      ...page,
      text: 'Later passage.',
      offset: 18,
      next_offset: null,
    });
  render(<RetainedSourceText incidentId="event" captureId="one" />);
  fireEvent.click(screen.getByRole('button', { name: 'Read retained source text' }));
  fireEvent.click(await screen.findByRole('button', { name: 'Read more source text' }));
  expect(await screen.findByRole('alert')).toHaveTextContent('Unavailable now.');
  expect(screen.getByText('Regional account.')).toBeVisible();
  fireEvent.click(screen.getByRole('button', { name: 'Retry source text' }));
  expect(await screen.findByText(/Later passage\./)).toBeVisible();
  expect(vi.mocked(fetchRetainedReporting).mock.calls[2].slice(0, 3)).toEqual([
    'event',
    'one',
    18,
  ]);
});

it('shows unavailable text explicitly', async () => {
  vi.mocked(fetchRetainedReporting).mockResolvedValueOnce({
    ...page,
    text: '',
    total_characters: 0,
    next_offset: null,
    unavailable_reason: 'No readable source text was retained.',
  });
  render(<RetainedSourceText incidentId="event" captureId="one" />);
  fireEvent.click(screen.getByRole('button', { name: 'Read retained source text' }));
  expect(
    await screen.findByText('No readable source text was retained.'),
  ).toBeVisible();
  expect(screen.queryByRole('button', { name: 'Read more source text' })).toBeNull();
});

it('aborts an outstanding capture read when the article is removed', async () => {
  vi.mocked(fetchRetainedReporting).mockImplementation(() => new Promise(() => {}));
  const view = render(<RetainedSourceText incidentId="event" captureId="one" />);
  fireEvent.click(screen.getByRole('button', { name: 'Read retained source text' }));
  await waitFor(() => expect(fetchRetainedReporting).toHaveBeenCalledOnce());
  const signal = vi.mocked(fetchRetainedReporting).mock.calls[0][3];
  view.unmount();
  expect(signal?.aborted).toBe(true);
});
