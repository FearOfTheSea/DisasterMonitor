import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { StandaloneEvidence } from '@/features/event-brief/ui/StandaloneEvidence';
import {
  fetchSectionEvidence,
  fetchInspectionExposure,
} from '@/features/event-brief/api/sectionEvidenceClient';
import type { StandaloneEvidenceResult } from '@/shared/api/generated/assistant';

vi.mock('@/features/event-brief/api/sectionEvidenceClient', () => ({
  fetchSectionEvidence: vi.fn(),
  fetchInspectionExposure: vi.fn(),
}));
afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});
const empty: StandaloneEvidenceResult = {
  event_id: 'provider:1',
  physical_event_id: 'physical:1',
  section: 'exposure',
  state: 'unconfigured',
  retrieved_at: '2026-10-11T03:00:00Z',
};

it('loads a standalone section and allows an explicit bounded inspection', async () => {
  vi.mocked(fetchSectionEvidence).mockResolvedValue(empty);
  vi.mocked(fetchInspectionExposure).mockResolvedValue(empty);
  render(<StandaloneEvidence identifier="provider:1" section="exposure" />);
  expect(
    await screen.findByText('This section requires operator configuration.'),
  ).toBeVisible();
  expect(fetchSectionEvidence).toHaveBeenCalledWith(
    'provider:1',
    'exposure',
    expect.any(AbortSignal),
  );
  fireEvent.click(screen.getByText('Inspect a supplied area'));
  ['West longitude', 'South latitude', 'East longitude', 'North latitude'].forEach(
    (label, index) => {
      fireEvent.change(screen.getByLabelText(label), {
        target: { value: [106, 10, 106.1, 10.1][index] },
      });
    },
  );
  fireEvent.click(
    screen.getByRole('button', { name: 'Calculate inspection exposure' }),
  );
  expect(fetchInspectionExposure).toHaveBeenCalledWith(
    'provider:1',
    [106, 10, 106.1, 10.1],
  );
});

it('explains an empty photo result with rejection categories', async () => {
  vi.mocked(fetchSectionEvidence).mockResolvedValue({
    ...empty,
    section: 'media',
    state: 'empty',
    media: {
      event_id: 'provider:1',
      physical_event_id: 'physical:1',
      generated_at: empty.retrieved_at,
      items: [],
      provider_ids: [],
      rejected_count: 3,
      rejection_reasons: [['location_mismatch', 3]],
    },
  });
  render(<StandaloneEvidence identifier="provider:1" section="media" />);
  expect(await screen.findByText(/location mismatch: 3/)).toBeVisible();
  expect(screen.getByText(/This does not establish absence/)).toBeVisible();
});
