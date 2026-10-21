import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { useState } from 'react';
import { afterEach, expect, it, vi } from 'vitest';
import { PhotographCollection } from '@/features/event-brief/ui/PhotographCollection';
import type { DisasterMediaGallery } from '@/shared/api/generated/assistant';

afterEach(cleanup);
const gallery: DisasterMediaGallery = {
  event_id: 'one',
  physical_event_id: 'one',
  generated_at: '2026-10-18T00:00:00Z',
  rejected_count: 1,
  provider_ids: ['fixture'],
  collection_limit: 72,
  candidate_count: 9,
  truncated: true,
  unavailable_sources: [
    {
      source_page_url: 'https://daily.example/restricted',
      publisher: 'Daily',
      detail: 'Restricted access',
    },
  ],
  items: Array.from({ length: 7 }, (_, i) => ({
    media_id: `image:${i}`,
    event_id: 'one',
    physical_event_id: 'one',
    source_id: 'news',
    publisher: 'Daily',
    source_page_url: `https://daily.example/${i}`,
    caption: `Flood rescue ${i}`,
    credit: 'Agency',
    credit_kind: 'agency',
    published_at: null,
    captured_at: null,
    license_name: null,
    license_url: null,
    rights_status: 'source_preview',
    role: 'rescue_effort',
    association_status: 'exact_event_link',
    association_rule_ids: [],
    association_detail: 'Collected article',
    uncertainty: 'Unverified photograph context',
    content_sha256: 'a'.repeat(64),
    width: 640,
    height: 360,
    source_references: [
      {
        source_page_url: `https://wire.example/${i}`,
        publisher: 'Wire',
        caption: 'Original caption',
        credit: 'Photographer',
        credit_kind: 'photographer',
        published_at: null,
        captured_at: null,
        rights_status: 'source_preview',
      },
    ],
  })),
};
it('pages eligible photographs and retains source links and credits after an image breaks', () => {
  render(<PhotographCollection gallery={gallery} />);
  expect(screen.getAllByRole('img')).toHaveLength(5);
  fireEvent.error(screen.getAllByRole('img')[0]);
  expect(screen.getByText(/Photograph unavailable/)).toBeVisible();
  expect(screen.getAllByRole('link', { name: /Daily/ })[0]).toHaveAttribute(
    'href',
    'https://daily.example/0',
  );
  expect(screen.getAllByText(/Photographer/).length).toBeGreaterThan(0);
  fireEvent.click(screen.getByRole('button', { name: 'Next photographs' }));
  expect(screen.getAllByRole('img')).toHaveLength(2);
  expect(screen.getByText(/Collection truncated/)).toBeVisible();
  expect(screen.getByText('Restricted access')).toBeVisible();
});

it('loads later batches, keeps earlier photographs after failure, and can return', async () => {
  const first = { ...gallery, next_cursor: 'next-batch' };
  const later = {
    ...gallery,
    next_cursor: null,
    items: [{ ...gallery.items[0], media_id: 'later', caption: 'Later photograph' }],
  };
  const loader = vi
    .fn()
    .mockRejectedValueOnce(new Error('Source changed. Restart photographs.'))
    .mockResolvedValue(later);
  function Harness() {
    const [current, setCurrent] = useState(first);
    return (
      <PhotographCollection
        gallery={current}
        onLoadBatch={async (cursor, signal) => {
          const next = cursor ? await loader(cursor, signal) : first;
          if (!signal.aborted) setCurrent(next);
        }}
      />
    );
  }
  render(<Harness />);
  fireEvent.click(
    screen.getByRole('button', { name: 'Continue photograph collection' }),
  );
  expect(await screen.findByText(/Source changed/)).toBeVisible();
  expect(screen.getAllByRole('img')).toHaveLength(5);
  fireEvent.click(
    screen.getByRole('button', { name: 'Continue photograph collection' }),
  );
  await waitFor(() =>
    expect(screen.getByRole('img', { name: 'Later photograph' })).toBeVisible(),
  );
  expect(loader).toHaveBeenLastCalledWith('next-batch', expect.any(AbortSignal));
  fireEvent.click(screen.getByRole('button', { name: 'Previous collected batch' }));
  await waitFor(() => expect(screen.getAllByRole('img')).toHaveLength(5));
});

it('aborts a pending photograph batch when its event is closed', () => {
  let requested: AbortSignal | undefined;
  const { unmount } = render(
    <PhotographCollection
      gallery={{ ...gallery, next_cursor: 'later' }}
      onLoadBatch={(_cursor, signal) => {
        requested = signal;
        return new Promise<void>(() => {});
      }}
    />,
  );
  const next = screen.getByRole('button', { name: 'Continue photograph collection' });
  fireEvent.click(next);
  expect(next).toBeDisabled();
  expect(requested?.aborted).toBe(false);
  unmount();
  expect(requested?.aborted).toBe(true);
});
