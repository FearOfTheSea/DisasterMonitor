import { cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, expect, it } from 'vitest';
import { ArticleCollection } from '@/features/incidents/ui/ArticleCollection';
import type { DiscoveryReportResponse } from '@/shared/api/generated/assistant';

afterEach(cleanup);

it('groups burn accounts under injuries while preserving subtype and overlapping counts', () => {
  const source = {
    source_id: 'news',
    publisher: 'Daily',
    title: 'Wildfire response',
    canonical_url: 'https://daily.example/fire',
    published_at: '2026-10-16T00:00:00Z',
    retrieved_at: '2026-10-17T00:00:00Z',
  };
  render(
    <ArticleCollection
      reports={[
        {
          source,
          claims: [
            {
              category: 'injuries',
              label: 'Injuries',
              value: '3',
              excerpt: 'Three people were injured.',
              qualifiers: [],
            },
            {
              category: 'injuries',
              label: 'Burn injuries',
              value: '0',
              excerpt: 'No responders suffered burns.',
              qualifiers: [],
            },
          ],
        },
      ]}
    />,
  );
  fireEvent.click(screen.getByText('Injuries · 2 accounts'));
  expect(screen.getByText('Injuries: 3')).toBeVisible();
  expect(screen.getByText('Burn injuries: 0')).toBeVisible();
  expect(screen.getByText('No responders suffered burns.')).toBeVisible();
  expect(screen.queryByText(/Differing accounts/)).toBeNull();
});

it('shows a shared episode account once outside the individual hazard impacts', () => {
  const source = {
    source_id: 'news',
    publisher: 'Daily',
    title: 'Joint disaster report',
    canonical_url: 'https://daily.example/joint',
    published_at: '2026-10-12T00:00:00Z',
    retrieved_at: '2026-10-13T00:00:00Z',
  };
  const report = {
    source,
    claims: [],
    episode_account: {
      account_id: 'episode:one',
      hazards: ['flood', 'landslide'],
      location: 'Riverton Province',
      event_date_wording: '30-09-2026',
      event_time: '2026-09-30T00:00:00Z',
      excerpt:
        'Floods and landslides affected Riverton Province. A total of 25 deaths were reported.',
      claims: [
        {
          category: 'fatalities',
          label: 'Fatalities',
          value: '25',
          excerpt: 'A total of 25 deaths were reported.',
          qualifiers: [],
        },
      ],
    },
  } as DiscoveryReportResponse;
  render(
    <ArticleCollection
      reports={[report, { ...report, mention_id: 'second-hazard' }]}
    />,
  );
  const individual = screen.getByRole('region', { name: 'Reported impacts' });
  expect(within(individual).getByText('Fatalities: Unknown')).toBeVisible();
  const joint = screen.getByRole('region', { name: 'Combined episode accounts' });
  expect(within(joint).getAllByText('Fatalities: 25')).toHaveLength(1);
  expect(
    within(joint).getByText(/not allocated to individual hazards or localities/),
  ).toBeVisible();
  expect(within(joint).getByRole('link', { name: /Daily/ })).toHaveAttribute(
    'href',
    source.canonical_url,
  );
});
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

it('distinguishes descriptive article locations from resolved administrative context', () => {
  render(
    <ArticleCollection
      reports={[{ ...reports[0], location: 'North and South Province' }]}
      mappedGeometry={{
        kind: 'area',
        coordinates: [
          { latitude: 8, longitude: -81 },
          { latitude: 9, longitude: -80 },
          { latitude: 8, longitude: -80 },
        ],
        source_id: 'place_lookup',
        estimated: true,
        description: 'Partial administrative context: North Province only.',
      }}
    />,
  );
  const locations = screen.getByRole('region', { name: 'Reported locations' });
  expect(
    within(locations).getByText(/Descriptive place; coordinates unavailable/),
  ).toBeVisible();
  expect(
    within(locations).getByText(/Partial administrative context: North Province only/),
  ).toBeVisible();
  expect(
    within(locations).getByText(
      /not an exact event location or measured affected area/,
    ),
  ).toBeVisible();
  expect(within(locations).queryByText(/Location unresolved for mapping/)).toBeNull();
});

it('keeps an unresolved mapping notice when neither articles nor the selected event have geometry', () => {
  render(
    <ArticleCollection reports={[{ ...reports[0], location: 'Uncertain district' }]} />,
  );
  expect(screen.getByText(/Location unresolved for mapping/)).toBeVisible();
});
