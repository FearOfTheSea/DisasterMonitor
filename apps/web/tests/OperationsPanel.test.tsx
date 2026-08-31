import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { OperationsPanel } from '@/features/operations/ui/OperationsPanel';
import {
  fetchCountryCatalogStatus,
  fetchEvidenceHistory,
  fetchProviderFreshness,
  recordOperatorReview,
  requestCountryCatalogUpdate,
} from '@/features/operations/api/operationsClient';

const incidentWatchUi = vi.hoisted(() => ({
  onSelectIncident: undefined as unknown,
}));

vi.mock('@/features/operations/api/operationsClient', () => ({
  fetchProviderFreshness: vi.fn(),
  fetchEvidenceHistory: vi.fn(),
  fetchCountryCatalogStatus: vi.fn(),
  requestCountryCatalogUpdate: vi.fn(),
  recordOperatorReview: vi.fn(),
}));

vi.mock('@/features/operations/ui/IncidentWatches', () => ({
  IncidentWatches: (props: { onSelectIncident: unknown }) => {
    incidentWatchUi.onSelectIncident = props.onSelectIncident;
    return <section aria-label="Incident watches fixture" />;
  },
}));

describe('OperationsPanel', () => {
  afterEach(() => cleanup());

  beforeEach(() => {
    vi.mocked(fetchProviderFreshness).mockResolvedValue([
      {
        source_id: 'global-warnings-vietnam-warnings',
        state: 'fresh',
        last_attempt_at: null,
        last_success_at: '2026-08-13T08:00:00Z',
        effective_at: '2026-08-13T08:00:00Z',
        age_seconds: 10,
        expected_freshness_seconds: 3600,
        consecutive_failures: 0,
        latest_error_code: null,
      },
    ]);
    vi.mocked(fetchEvidenceHistory).mockResolvedValue([
      {
        snapshot_id: 'source-snapshot:1',
        source_id: 'global-warnings-vietnam-warnings',
        provider_revision: 'warning-1',
        retrieved_at: '2026-08-13T08:00:00Z',
        published_at: '2026-08-13T08:00:00Z',
        observed_at: null,
        effective_at: '2026-08-13T08:00:00Z',
        content_type: 'application/rss+xml',
        payload_sha256: `sha256:${'a'.repeat(64)}`,
        payload_size_bytes: 20,
        rights_id: 'global-warnings-rss-terms-2026-08',
        content_available: true,
        content_deleted_at: null,
        content_deletion_reason: null,
      },
    ]);
    const catalog = {
      state: 'unchanged' as const,
      active_version: 'natural-earth-5.1.2.tzdb-2026b.abc123',
      country_count: 242,
      automatic_updates_enabled: true,
      trigger: 'scheduled' as const,
      last_attempt_at: '2026-08-13T08:00:00Z',
      last_success_at: '2026-08-13T08:00:00Z',
      next_scheduled_at: '2026-09-01T00:00:00Z',
      message: 'The latest validated catalog is active.',
      failure_code: null,
      sources: [
        {
          source_id: 'natural-earth-admin-0',
          version: 'v5.1.2',
          revision: 'a'.repeat(40),
          sha256: `sha256:${'b'.repeat(64)}`,
        },
      ],
    };
    vi.mocked(fetchCountryCatalogStatus).mockResolvedValue(catalog);
    vi.mocked(requestCountryCatalogUpdate).mockResolvedValue({
      ...catalog,
      state: 'updated',
      trigger: 'manual',
      message: 'Promoted the latest catalog.',
    });
    vi.mocked(recordOperatorReview).mockResolvedValue({
      action_id: 'operator-action:1',
      operator_id: 'operator-7',
      state_version: 'world-state:1',
      decision: 'reviewed',
      reviewed_at: '2026-08-13T08:00:00Z',
      created: true,
    });
  });

  it('shows provenance and records a bounded review', async () => {
    const user = userEvent.setup();
    const onSelectWatchIncident = vi.fn();
    render(
      <OperationsPanel
        evidenceStateVersion="world-state:1"
        onClose={vi.fn()}
        onSelectWatchIncident={onSelectWatchIncident}
      />,
    );

    expect(screen.getByLabelText('Incident watches fixture')).toBeInTheDocument();
    expect(incidentWatchUi.onSelectIncident).toBe(onSelectWatchIncident);
    expect(await screen.findAllByText('global-warnings-vietnam-warnings')).toHaveLength(
      2,
    );
    expect(screen.getByText('242 active countries')).toBeInTheDocument();
    expect(screen.getByText('Content retained')).toBeInTheDocument();
    expect(screen.getByText('Status: fresh')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Update countries now' }));
    expect(await screen.findByText('Promoted the latest catalog.')).toBeInTheDocument();
    expect(requestCountryCatalogUpdate).toHaveBeenCalledOnce();
    await user.type(screen.getByLabelText('Review rationale'), 'Checked freshness.');
    await user.click(screen.getByRole('button', { name: 'Record review' }));

    await waitFor(() =>
      expect(recordOperatorReview).toHaveBeenCalledWith(
        'world-state:1',
        'Checked freshness.',
      ),
    );
    expect(
      await screen.findByText('Review recorded for operator-7.'),
    ).toBeInTheDocument();
  });

  it('summarizes and orders source health without implying coverage for degraded states', async () => {
    vi.mocked(fetchProviderFreshness).mockResolvedValue([
      {
        source_id: 'zulu-fresh',
        state: 'fresh',
        last_attempt_at: '2026-08-13T08:01:00Z',
        last_success_at: '2026-08-13T08:00:00Z',
        effective_at: '2026-08-13T08:00:00Z',
        age_seconds: 60,
        expected_freshness_seconds: 3600,
        consecutive_failures: 0,
        latest_error_code: null,
      },
      {
        source_id: 'alpha-never',
        state: 'never_ingested',
        last_attempt_at: null,
        last_success_at: null,
        effective_at: null,
        age_seconds: null,
        expected_freshness_seconds: 900,
        consecutive_failures: 0,
        latest_error_code: null,
      },
      {
        source_id: 'bravo-unavailable',
        state: 'unavailable',
        last_attempt_at: '2026-08-13T07:55:00Z',
        last_success_at: '2026-08-13T06:00:00Z',
        effective_at: '2026-08-13T06:00:00Z',
        age_seconds: 7260,
        expected_freshness_seconds: 3600,
        consecutive_failures: 3,
        latest_error_code: 'timeout',
      },
      {
        source_id: 'charlie-stale',
        state: 'stale',
        last_attempt_at: '2026-08-13T07:59:00Z',
        last_success_at: '2026-08-13T06:30:00Z',
        effective_at: '2026-08-13T06:30:00Z',
        age_seconds: 5460,
        expected_freshness_seconds: 1800,
        consecutive_failures: 1,
        latest_error_code: null,
      },
    ]);

    render(<OperationsPanel onClose={vi.fn()} onSelectWatchIncident={vi.fn()} />);

    expect(await screen.findByText(/Sources 4/)).toBeInTheDocument();
    expect(screen.getByText(/Fresh 1/)).toBeInTheDocument();
    expect(screen.getByText(/Stale 1/)).toBeInTheDocument();
    expect(screen.getByText(/Unavailable 1/)).toBeInTheDocument();
    expect(screen.getByText(/Never ingested 1/)).toBeInTheDocument();
    const sourceNames = screen
      .getAllByTestId('provider-source')
      .map((node) => node.textContent);
    expect(sourceNames).toEqual([
      'alpha-never',
      'bravo-unavailable',
      'charlie-stale',
      'zulu-fresh',
    ]);
    expect(screen.getByText('Evidence age: 1h 31m')).toBeInTheDocument();
    expect(screen.getAllByText('Expected interval: 1h')).toHaveLength(2);
    expect(screen.getByText('Consecutive failures: 3')).toBeInTheDocument();
    expect(screen.getByText('Latest error: timeout')).toBeInTheDocument();
    expect(screen.getByText('Evidence time: Never')).toBeInTheDocument();
    expect(screen.getByText('Status: never ingested')).toBeInTheDocument();
  });

  it('shows an empty state and refreshes the existing provider request', async () => {
    const user = userEvent.setup();
    vi.mocked(fetchProviderFreshness).mockResolvedValue([]);
    render(<OperationsPanel onClose={vi.fn()} onSelectWatchIncident={vi.fn()} />);
    expect(
      await screen.findByText('No provider freshness records are available.'),
    ).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Refresh source health' }));
    expect(fetchProviderFreshness).toHaveBeenCalled();
  });
});
