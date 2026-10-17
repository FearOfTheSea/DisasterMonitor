import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, expect, it } from 'vitest';
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
