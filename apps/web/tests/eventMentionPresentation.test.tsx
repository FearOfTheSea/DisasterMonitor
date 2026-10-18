import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { DiscoveryScanControls } from '@/features/incidents/ui/DiscoveryScanControls';
import { ArticleCollection } from '@/features/incidents/ui/ArticleCollection';
import type { DiscoveryScanResponse } from '@/shared/api/generated/assistant';

afterEach(cleanup);

it('separates reports, unresolved candidates and associated events', () => {
  render(
    <DiscoveryScanControls
      days={7}
      onDaysChange={vi.fn()}
      onScan={vi.fn()}
      run={
        {
          status: 'completed',
          interval_start: '2026-10-11T12:00:00Z',
          interval_end: '2026-10-18T12:00:00Z',
          snapshot: { incidents: [] },
          reports_seen: 81,
          candidate_count: 12,
          associated_event_count: 8,
          uncertain_publication_count: 2,
          issues: [],
        } as unknown as DiscoveryScanResponse
      }
    />,
  );
  expect(screen.getByText(/8 associated physical events/)).toBeVisible();
  expect(screen.getByText(/12 unresolved event candidates/)).toBeVisible();
  expect(screen.getByText(/81 collected reports/)).toBeVisible();
  expect(screen.getByText(/2 reports overlap/)).toBeVisible();
});

it('shows date-only publication and mention evidence without a fabricated clock', () => {
  render(
    <ArticleCollection
      reports={[
        {
          source: {
            source_id: 'news',
            publisher: 'Daily',
            title: 'Flood update',
            canonical_url: 'https://news.example/a',
            published_at: '2026-10-17T00:00:00Z',
            publication_precision: 'day',
            retrieved_at: '2026-10-18T12:00:00Z',
          },
          mention_id: 'mention:1',
          mention_excerpt: 'Floods hit Riverton on 9 October.',
          mention_role: 'historical',
          event_date_wording: '9 October',
          event_date_precision: 'day',
          event_time: '2026-10-09T00:00:00Z',
          location: 'Riverton',
          location_precision: 'named_place',
        },
      ]}
    />,
  );
  expect(
    screen.getByText(/Published: 2026-10-17 \(date only; exact time unknown\)/),
  ).toBeVisible();
  expect(screen.getByText('Floods hit Riverton on 9 October.')).toBeVisible();
  expect(screen.getByText(/historical mention/)).toBeVisible();
});
