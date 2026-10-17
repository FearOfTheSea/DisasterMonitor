import { act, cleanup, render, screen } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { StandaloneEvidence } from '@/features/event-brief/ui/StandaloneEvidence';
import type { StandaloneEvidenceResult } from '@/shared/api/generated/assistant';

const api = vi.hoisted(() => ({ fetchSectionEvidence: vi.fn() }));
vi.mock('@/features/event-brief/api/sectionEvidenceClient', () => api);
afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

it('keeps a late photograph request under its original event', async () => {
  let finish: (result: StandaloneEvidenceResult) => void = () => undefined;
  api.fetchSectionEvidence.mockImplementationOnce(
    () =>
      new Promise((resolve) => {
        finish = resolve;
      }),
  );
  const result: StandaloneEvidenceResult = {
    event_id: 'new',
    physical_event_id: 'new',
    section: 'media',
    state: 'empty',
    retrieved_at: '2026-10-18T00:00:00Z',
    narratives: ['NEW account'],
  };
  api.fetchSectionEvidence.mockResolvedValueOnce(result);
  const view = render(<StandaloneEvidence identifier="old" section="media" />);
  view.rerender(<StandaloneEvidence identifier="new" section="media" />);
  expect(await screen.findByText('NEW account')).toBeVisible();
  await act(async () =>
    finish({ ...result, event_id: 'old', narratives: ['OLD account'] }),
  );
  expect(screen.queryByText('OLD account')).toBeNull();
});
