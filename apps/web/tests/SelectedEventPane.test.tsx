import { cleanup, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';

import type { IncidentMapRecord } from '@/features/incidents/model/activeIncidents';
import { SelectedEventPane } from '@/features/incidents/ui/SelectedEventPane';

const INCIDENT: IncidentMapRecord = {
  event_id: 'fixture:one',
  disaster: 'earthquake',
  country: null,
  location: 'Fixture location',
  event_time: '2026-09-23T03:00:00Z',
  geometry: null,
  measurements: [
    { kind: 'magnitude', value: 6.2, unit: null, source_id: 'fixture-source' },
  ],
  provider_ids: ['fixture:one'],
  provider_tier: 'primary',
  source_authority: 'scientific_authority',
  source: {
    source_id: 'fixture-source',
    publisher: 'Fixture publisher',
    title: 'Fixture source record',
    canonical_url: 'https://example.test/source',
    published_at: '2026-09-23T04:00:00Z',
    updated_at: null,
    retrieved_at: '2026-09-23T05:00:00Z',
    snapshot_id: null,
  },
};

afterEach(cleanup);

describe('selected event reading pane', () => {
  it.each(['reported', 'uncertain'] as const)(
    'does not describe an article headline as the %s event location',
    (role) => {
      const headline = 'Regional news roundup and recovery updates';
      render(
        <SelectedEventPane
          incident={{
            ...INCIDENT,
            location: headline,
            source: { ...INCIDENT.source, title: headline },
            discovery_reports: [
              {
                source: { ...INCIDENT.source, title: headline },
                mention_role: role,
                location: null,
              },
            ],
          }}
          snapshotRetrievedAt="2026-10-23T12:00:00Z"
          onClose={vi.fn()}
          onAsk={vi.fn()}
          onGroundView={vi.fn()}
        />,
      );
      expect(screen.getByText(/The reported place is unresolved/)).toBeVisible();
      expect(screen.queryByText(/at Regional news roundup/)).not.toBeInTheDocument();
      expect(screen.getAllByText(headline).length).toBeGreaterThan(0);
    },
  );

  it('keeps a literal reported place that is also the short article headline', () => {
    render(
      <SelectedEventPane
        incident={{
          ...INCIDENT,
          location: 'Lakeview',
          source: { ...INCIDENT.source, title: 'Lakeview' },
          discovery_reports: [
            { source: INCIDENT.source, mention_role: 'reported', location: 'Lakeview' },
          ],
        }}
        snapshotRetrievedAt="2026-10-23T12:00:00Z"
        onClose={vi.fn()}
        onAsk={vi.fn()}
        onGroundView={vi.fn()}
      />,
    );
    expect(screen.getByText(/reports an earthquake at Lakeview/)).toBeVisible();
    expect(
      screen.queryByText(/The reported place is unresolved/),
    ).not.toBeInTheDocument();
  });

  it('shows a reported month as a period without inventing its first day as onset', () => {
    render(
      <SelectedEventPane
        incident={{
          ...INCIDENT,
          event_time: '2021-12-01T00:00:00Z',
          event_time_end: '2022-01-01T00:00:00Z',
          event_time_precision: 'range',
        }}
        snapshotRetrievedAt="2026-10-22T00:00:00Z"
        onClose={vi.fn()}
        onAsk={vi.fn()}
        onGroundView={vi.fn()}
      />,
    );
    expect(screen.getByText('December 2021 (exact date unresolved)')).toBeVisible();
    expect(screen.queryByText(/2021-12-01.*date only/)).not.toBeInTheDocument();
  });

  it('keeps supported occurrence wording when an ongoing report has contextual evidence', () => {
    render(
      <SelectedEventPane
        incident={{
          ...INCIDENT,
          identity_status: 'associated',
          discovery_reports: [
            { source: INCIDENT.source, mention_role: 'ongoing' },
            { source: INCIDENT.source, mention_role: 'uncertain' },
          ],
        }}
        snapshotRetrievedAt="2026-09-23T05:00:00Z"
        onClose={vi.fn()}
        onAsk={vi.fn()}
        onGroundView={vi.fn()}
      />,
    );
    expect(screen.getByText(/reports an earthquake at Fixture location/)).toBeVisible();
    expect(screen.getByText(/Associated physical event/)).toBeVisible();
    expect(screen.queryByText(/Retained source context/)).not.toBeInTheDocument();
  });

  it.each(['uncertain', 'forecast', 'historical'] as const)(
    'keeps %s source context from becoming a physical-event assertion',
    (role) => {
      render(
        <SelectedEventPane
          incident={{
            ...INCIDENT,
            event_time: null,
            event_time_basis: 'unknown',
            identity_status: 'candidate',
            measurements: [],
            verification_status: 'provisional_news_detected',
            discovery_reports: [
              {
                source: INCIDENT.source,
                mention_role: role,
                mention_excerpt: 'Retained passage with unresolved occurrence scope.',
                fatality_evidence: [],
              },
            ],
          }}
          snapshotRetrievedAt="2026-09-23T05:00:00Z"
          onClose={vi.fn()}
          onAsk={vi.fn()}
          onGroundView={vi.fn()}
        />,
      );
      expect(screen.getByText(/Retained source context/)).toBeVisible();
      expect(
        screen.getByText(/does not establish a current earthquake occurrence/),
      ).toBeVisible();
      expect(screen.queryByText(/reports an earthquake at/)).not.toBeInTheDocument();
      expect(screen.queryByText(/Unresolved event candidate/)).not.toBeInTheDocument();
      expect(
        screen.getByText('Retained passage with unresolved occurrence scope.'),
      ).toBeVisible();
    },
  );

  it('focuses source-backed content without asking the assistant until requested', async () => {
    const onAsk = vi.fn();
    render(
      <SelectedEventPane
        incident={INCIDENT}
        snapshotRetrievedAt="2026-09-23T05:00:00Z"
        onClose={vi.fn()}
        onAsk={onAsk}
        onGroundView={vi.fn()}
      />,
    );
    expect(screen.getByRole('heading', { name: /Earthquake/ })).toHaveFocus();
    expect(screen.getByText(/reports an earthquake at Fixture location/)).toBeVisible();
    expect(screen.getByText('6.2')).toBeVisible();
    expect(screen.getByRole('link', { name: /Fixture publisher/ })).toHaveAttribute(
      'href',
      'https://example.test/source',
    );
    expect(onAsk).not.toHaveBeenCalled();
    await userEvent.setup().click(screen.getByRole('tab', { name: 'Evidence' }));
    expect(screen.getByText('Provenance')).toBeVisible();
    await userEvent.setup().click(screen.getByRole('tab', { name: 'Timeline' }));
    expect(screen.getByText('Source publication')).toBeVisible();
    await userEvent.setup().click(screen.getByRole('tab', { name: 'Overview' }));
    await userEvent
      .setup()
      .click(screen.getByRole('button', { name: 'Ask about worldwide earthquakes' }));
    expect(onAsk).toHaveBeenCalledOnce();
  });

  it('moves among detail tabs with arrow keys', async () => {
    const user = userEvent.setup();
    render(
      <SelectedEventPane
        incident={INCIDENT}
        snapshotRetrievedAt="2026-09-23T05:00:00Z"
        onClose={vi.fn()}
        onAsk={vi.fn()}
        onGroundView={vi.fn()}
      />,
    );
    const overview = screen.getByRole('tab', { name: 'Overview' });
    const evidence = screen.getByRole('tab', { name: 'Evidence' });
    const timeline = screen.getByRole('tab', { name: 'Timeline' });
    overview.focus();
    await user.keyboard('{ArrowRight}');
    expect(evidence).toHaveFocus();
    expect(evidence).toHaveAttribute('aria-selected', 'true');
    await user.keyboard('{End}');
    expect(timeline).toHaveFocus();
    expect(screen.getByText('Source publication')).toBeVisible();
  });

  it('groups equal measurements while keeping differing source values visible', () => {
    render(
      <SelectedEventPane
        incident={{
          ...INCIDENT,
          measurements: [
            { kind: 'magnitude', value: 5.6, unit: null, source_id: 'usgs' },
            { kind: 'magnitude', value: 5.6, unit: null, source_id: 'emsc' },
            { kind: 'magnitude', value: 5.6, unit: null, source_id: 'gdacs' },
            { kind: 'depth', value: 10, unit: 'km', source_id: 'emsc' },
            { kind: 'depth', value: 57.78, unit: 'km', source_id: 'usgs' },
          ],
        }}
        snapshotRetrievedAt="2026-09-23T05:00:00Z"
        onClose={vi.fn()}
        onAsk={vi.fn()}
        onGroundView={vi.fn()}
      />,
    );

    expect(screen.getAllByText('magnitude')).toHaveLength(1);
    expect(screen.getByText(/3 sources: usgs, emsc, gdacs/)).toBeInTheDocument();
    expect(screen.getByText(/10 km/)).toBeInTheDocument();
    expect(screen.getByText(/57.78 km/)).toBeInTheDocument();
  });
});
