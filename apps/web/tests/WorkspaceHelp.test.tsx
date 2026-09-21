import { cleanup, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it } from 'vitest';

import { WorkspaceHelp } from '@/features/help/ui/WorkspaceHelp';

afterEach(cleanup);

describe('WorkspaceHelp', () => {
  it('reveals and closes a concise reading guide', async () => {
    const user = userEvent.setup();
    render(<WorkspaceHelp />);

    await user.click(screen.getByRole('button', { name: 'Open help' }));

    const guide = screen.getByRole('dialog', { name: 'How to use Disaster Monitor' });
    expect(guide).toHaveTextContent('Start with the incident list');
    expect(guide).toHaveTextContent('Coverage describes source checks');
    expect(guide).toHaveTextContent('Map options change only what is displayed');

    await user.click(within(guide).getByRole('button', { name: 'Close help guide' }));
    expect(
      screen.queryByRole('dialog', { name: 'How to use Disaster Monitor' }),
    ).not.toBeInTheDocument();
  });
});
