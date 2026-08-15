import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { OperationsPanel } from '@/features/operations/ui/OperationsPanel';
import {
  fetchEvidenceHistory,
  fetchProviderFreshness,
  recordOperatorReview,
} from '@/features/operations/api/operationsClient';

vi.mock('@/features/operations/api/operationsClient', () => ({
  fetchProviderFreshness: vi.fn(),
  fetchEvidenceHistory: vi.fn(),
  recordOperatorReview: vi.fn(),
}));

describe('OperationsPanel', () => {
  beforeEach(() => {
    vi.mocked(fetchProviderFreshness).mockResolvedValue([
      {
        source_id: 'nchmf-vietnam-warnings',
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
        source_id: 'nchmf-vietnam-warnings',
        provider_revision: 'warning-1',
        retrieved_at: '2026-08-13T08:00:00Z',
        published_at: '2026-08-13T08:00:00Z',
        observed_at: null,
        effective_at: '2026-08-13T08:00:00Z',
        content_type: 'application/rss+xml',
        payload_sha256: `sha256:${'a'.repeat(64)}`,
        payload_size_bytes: 20,
        rights_id: 'nchmf-rss-terms-2026-08',
        content_available: true,
        content_deleted_at: null,
        content_deletion_reason: null,
      },
    ]);
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
    render(<OperationsPanel evidenceStateVersion="world-state:1" onClose={vi.fn()} />);

    expect(await screen.findAllByText('nchmf-vietnam-warnings')).toHaveLength(2);
    expect(screen.getByText('Content retained')).toBeInTheDocument();
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
});
