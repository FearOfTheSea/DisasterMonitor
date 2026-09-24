import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import {
  addAnalystNote,
  addBookmark,
  createRunbook,
  fetchOperatorWorkspace,
} from '@/features/operations/api/operatorWorkspaceClient';
import { OperatorWorkspace } from '@/features/operations/ui/OperatorWorkspace';

vi.mock('@/features/operations/api/operatorWorkspaceClient', () => ({
  addAnalystNote: vi.fn(),
  addBookmark: vi.fn(),
  createRunbook: vi.fn(),
  fetchOperatorWorkspace: vi.fn(),
}));

const workspace = {
  boundary: 'non_evidence_operator_state' as const,
  incident_id: 'event-1',
  notes: [
    {
      note_id: 'note:one',
      incident_id: 'event-1',
      text: 'Call the district desk.',
      tags: ['handoff'],
      created_at: '2026-09-16T08:00:00Z',
      evidence: false as const,
    },
  ],
  bookmarks: [],
  runbooks: [],
};

describe('OperatorWorkspace', () => {
  afterEach(() => cleanup());

  beforeEach(() => {
    vi.mocked(fetchOperatorWorkspace).mockResolvedValue(workspace);
    vi.mocked(addAnalystNote).mockResolvedValue(workspace.notes[0]);
    vi.mocked(addBookmark).mockResolvedValue({
      bookmark_id: 'bookmark:one',
      incident_id: 'event-1',
      target_type: 'source',
      target_id: 'snapshot:one',
      label: 'Situation report',
      created_at: '2026-09-16T08:00:00Z',
      evidence: false,
    });
    vi.mocked(createRunbook).mockResolvedValue({
      template_id: 'runbook:one',
      name: 'Review checklist',
      steps: ['Inspect finding:one'],
      created_at: '2026-09-16T08:00:00Z',
      autonomous_actions: false,
    });
  });

  it('makes the non-evidence boundary visible and adds tagged notes', async () => {
    const user = userEvent.setup();
    render(<OperatorWorkspace selectedIncidentId="event-1" />);

    expect(await screen.findByText('Non-evidence operator state')).toBeInTheDocument();
    expect(await screen.findByText('Call the district desk.')).toBeInTheDocument();
    await user.click(screen.getByText('Add note, bookmark, or checklist'));
    await user.type(screen.getByLabelText('Analyst note'), 'Confirm bridge access.');
    await user.type(screen.getByLabelText('Note tags'), 'handoff, access');
    await user.click(screen.getByRole('button', { name: 'Save non-evidence note' }));

    await waitFor(() =>
      expect(addAnalystNote).toHaveBeenCalledWith({
        incident_id: 'event-1',
        text: 'Confirm bridge access.',
        tags: ['handoff', 'access'],
      }),
    );
  });
});
