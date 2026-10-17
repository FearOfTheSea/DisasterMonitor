import { cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, expect, it } from 'vitest';
import { ArticleCollection } from '@/features/incidents/ui/ArticleCollection';
import type { DiscoveryReportResponse } from '@/shared/api/generated/assistant';

afterEach(cleanup);
const reports: DiscoveryReportResponse[] = Array.from({ length: 8 }, (_, i) => ({
  source: {
    source_id: 'news',
    publisher: 'Daily',
    title: `Article ${i}`,
    canonical_url: `https://daily.example/${i}`,
    published_at: i === 7 ? null : `2026-10-${10 + i}T12:00:00Z`,
    retrieved_at: '2026-10-18T12:00:00Z',
  },
  indexed_at: '2026-10-18T11:00:00Z',
  origin: 'wire:shared',
  claims: [
    {
      category: 'fatalities',
      label: 'Fatalities',
      value: i === 0 ? '0' : '12',
      excerpt: `Account ${i} in North Province on Monday.`,
      qualifiers: i === 0 ? ['corrected'] : ['preliminary'],
    },
  ],
}));

it('shows five latest publications and pages every remaining report, separating unknown dates', async () => {
  const user = userEvent.setup();
  render(
    <ArticleCollection
      reports={reports}
      notices={['Collection limited to retained reports.']}
    />,
  );
  const dated = screen.getByRole('region', { name: 'Dated articles' });
  expect(within(dated).getAllByRole('link')).toHaveLength(5);
  expect(within(dated).getAllByRole('link')[0]).toHaveTextContent('Article 6');
  expect(within(dated).queryByText(/Article 1/)).toBeNull();
  screen.getByRole('button', { name: 'Next articles' }).focus();
  await user.keyboard('{Enter}');
  expect(within(dated).getAllByRole('link')).toHaveLength(2);
  expect(within(dated).getByRole('link', { name: /Article 0/ })).toHaveAttribute(
    'href',
    'https://daily.example/0',
  );
  expect(screen.getByText(/Unknown publication times/)).toBeVisible();
  fireEvent.click(screen.getByText(/Unknown publication times/));
  expect(screen.getByRole('link', { name: /Article 7/ })).toBeVisible();
  fireEvent.click(screen.getByText('Collection and access limits'));
  expect(screen.getByText('Collection limited to retained reports.')).toBeVisible();
});

it('preserves all attributed conflicting accounts independently of article pages', () => {
  render(<ArticleCollection reports={reports} />);
  fireEvent.click(screen.getByText(/Fatalities ·/));
  expect(screen.getByText(/Differing accounts/)).toBeVisible();
  expect(screen.getByText(/Counts are not added/)).toBeVisible();
  expect(screen.getByText('Account 0 in North Province on Monday.')).toBeVisible();
  expect(screen.getByText(/Fatalities: 0/)).toBeVisible();
  expect(screen.getAllByText(/corrected/).length).toBeGreaterThan(0);
  expect(screen.getByText(/Injuries: Unknown/)).toBeVisible();
});
