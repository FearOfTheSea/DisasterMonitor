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
      .click(screen.getByRole('button', { name: 'Ask about this event' }));
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
});
