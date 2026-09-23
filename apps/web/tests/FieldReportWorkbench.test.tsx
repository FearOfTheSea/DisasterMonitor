import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import {
  createFieldReport,
  fetchDuplicateCandidates,
  fetchFieldReports,
  fetchFieldReviewCapability,
  reviewFieldReport,
} from '@/features/operations/api/fieldReportsClient';
import { FieldReportWorkbench } from '@/features/operations/ui/FieldReportWorkbench';

vi.mock('@/features/operations/api/fieldReportsClient', () => ({
  createFieldReport: vi.fn(),
  fetchDuplicateCandidates: vi.fn(),
  fetchFieldReports: vi.fn(),
  fetchFieldReviewCapability: vi.fn(),
  reviewFieldReport: vi.fn(),
}));

const report = {
  report_id: 'field-report:one',
  report_type: 'road_blocked',
  text: 'Water is covering the road beside the bridge.',
  captured_at: '2026-09-16T07:45:00Z',
  source_created_at: '2026-09-16T07:50:00Z',
  received_at: '2026-09-16T08:00:00Z',
  submitter_channel: 'operator-form',
  geometry: {
    kind: 'point' as const,
    coordinates: [{ longitude: 106, latitude: 21 }],
  },
  location_precision: 'approximate' as const,
  location_uncertainty_m: 100,
  media: [],
  import_provenance: null,
  review_state: 'pending_review' as const,
  authority: 'unverified' as const,
  tags: [],
  associated_event_id: null,
  review_revision: 0,
};

describe('FieldReportWorkbench', () => {
  afterEach(() => cleanup());

  beforeEach(() => {
    vi.mocked(fetchFieldReports).mockResolvedValue([report]);
    vi.mocked(fetchFieldReviewCapability).mockResolvedValue({
      available: true,
      reason: null,
    });
    vi.mocked(fetchDuplicateCandidates).mockResolvedValue([
      {
        candidate_id: 'duplicate:one',
        report_ids: ['field-report:one', 'field-report:two'],
        time_delta_seconds: 300,
        distance_km: 0.4,
        same_type: true,
        score: 0.91,
        auto_merge: false,
      },
    ]);
    vi.mocked(createFieldReport).mockResolvedValue(report);
    vi.mocked(reviewFieldReport).mockResolvedValue({
      report: { ...report, review_state: 'associated', associated_event_id: 'event-1' },
      review: {
        review_id: 'field-review:one',
        report_id: report.report_id,
        decision: 'associate_to_event',
        reviewer_id: 'operator:local',
        rationale: 'Matches the selected event in time and place.',
        reviewed_at: '2026-09-16T08:05:00Z',
        event_id: 'event-1',
        authority_policy_id: null,
        revision: 1,
      },
      operator_observation: null,
    });
  });

  it('submits point reports as unverified with explicit time and uncertainty', async () => {
    const user = userEvent.setup();
    render(<FieldReportWorkbench selectedIncidentId="event-1" />);
    await screen.findByText('Water is covering the road beside the bridge.');

    await user.selectOptions(screen.getByLabelText('Report type'), 'flooding');
    await user.type(screen.getByLabelText('Field report text'), 'Floodwater rising.');
    await user.clear(screen.getByLabelText('Captured at'));
    await user.type(screen.getByLabelText('Captured at'), '2026-09-16T07:30');
    await user.clear(screen.getByLabelText('Source created at'));
    await user.type(screen.getByLabelText('Source created at'), '2026-09-16T07:35');
    await user.clear(screen.getByLabelText('Longitude'));
    await user.type(screen.getByLabelText('Longitude'), '106.1');
    await user.clear(screen.getByLabelText('Latitude'));
    await user.type(screen.getByLabelText('Latitude'), '21.1');
    await user.clear(screen.getByLabelText('Location uncertainty in metres'));
    await user.type(screen.getByLabelText('Location uncertainty in metres'), '250');
    await user.click(screen.getByRole('button', { name: 'Submit unverified report' }));

    await waitFor(() => expect(createFieldReport).toHaveBeenCalledOnce());
    expect(createFieldReport).toHaveBeenCalledWith(
      expect.objectContaining({
        report_type: 'flooding',
        text: 'Floodwater rising.',
        submitter_channel: 'operator-form',
        location_precision: 'approximate',
        location_uncertainty_m: 250,
        geometry: { type: 'Point', coordinates: [106.1, 21.1] },
        attachments: [],
      }),
    );
    expect(await screen.findByText('Report queued as unverified.')).toBeInTheDocument();
  });

  it('keeps duplicate decisions human and supports explicit association review', async () => {
    const user = userEvent.setup();
    render(<FieldReportWorkbench selectedIncidentId="event-1" />);

    expect(
      await screen.findByText('Possible duplicate · never auto-merged'),
    ).toBeInTheDocument();
    await user.selectOptions(
      screen.getByLabelText('Review decision for field-report:one'),
      'associate_to_event',
    );
    await user.type(
      screen.getByLabelText('Review rationale for field-report:one'),
      'Matches the selected event in time and place.',
    );
    await user.click(
      screen.getByRole('button', { name: 'Record field report review' }),
    );

    await waitFor(() =>
      expect(reviewFieldReport).toHaveBeenCalledWith(
        'field-report:one',
        expect.objectContaining({
          decision: 'associate_to_event',
          event_id: 'event-1',
          authority_policy_id: null,
        }),
      ),
    );
  });

  it('disables review when trusted identity is unavailable', async () => {
    vi.mocked(fetchFieldReviewCapability).mockResolvedValue({
      available: false,
      reason: 'not_configured',
    });
    render(<FieldReportWorkbench selectedIncidentId="event-1" />);
    expect(await screen.findByText(/Review is unavailable until/)).toBeInTheDocument();
    expect(
      screen.getByRole('button', { name: 'Record field report review' }),
    ).toBeDisabled();
  });
});
