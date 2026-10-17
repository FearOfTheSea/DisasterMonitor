import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { expect, it, vi } from 'vitest';
import { NotebookEditor } from '@/features/operations/ui/NotebookEditor';
import { createNotebook } from '@/features/operations/api/operatorWorkspaceClient';
vi.mock('@/features/operations/api/operatorWorkspaceClient', () => ({
  createNotebook: vi.fn(),
  fetchNotebookEntries: vi.fn().mockResolvedValue([]),
  addNotebookEntry: vi.fn(),
}));
it('creates a non-evidence notebook using the desktop editor', async () => {
  vi.mocked(createNotebook).mockResolvedValue({
    notebook_id: 'notebook:1',
    title: 'Flood review',
    created_by: 'local-operator',
    created_at: '2026-10-11T00:00:00Z',
    incident_ids: [],
    evidence: false,
  });
  render(<NotebookEditor notebooks={[]} onSaved={() => {}} />);
  await userEvent.type(screen.getByLabelText('New notebook title'), 'Flood review');
  await userEvent.click(screen.getByRole('button', { name: 'Create notebook' }));
  expect(createNotebook).toHaveBeenCalledWith(
    expect.objectContaining({ title: 'Flood review', created_by: 'local-operator' }),
  );
});
