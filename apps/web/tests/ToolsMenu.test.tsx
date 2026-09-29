import { cleanup, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { ToolsMenu } from '@/app/workspace/ToolsMenu';

afterEach(() => cleanup());

describe('desktop Tools menu', () => {
  it('moves focus with keyboard controls and restores it on Escape', async () => {
    const user = userEvent.setup();
    render(<ToolsMenu onSelect={vi.fn()} />);

    const trigger = screen.getByRole('button', { name: 'Tools' });
    await user.click(trigger);
    expect(screen.getByRole('menuitem', { name: 'Field reports' })).toHaveFocus();
    await user.keyboard('{ArrowDown}');
    expect(screen.getByRole('menuitem', { name: 'Workspace' })).toHaveFocus();
    await user.keyboard('{End}');
    expect(screen.getByRole('menuitem', { name: 'Maintenance' })).toHaveFocus();
    await user.keyboard('{Home}');
    expect(screen.getByRole('menuitem', { name: 'Field reports' })).toHaveFocus();
    await user.keyboard('{Escape}');
    expect(trigger).toHaveFocus();
    expect(trigger).toHaveAttribute('aria-expanded', 'false');
  });

  it('selects a section and closes the menu', async () => {
    const user = userEvent.setup();
    const onSelect = vi.fn();
    render(<ToolsMenu onSelect={onSelect} />);

    await user.click(screen.getByRole('button', { name: 'Tools' }));
    await user.click(screen.getByRole('menuitem', { name: 'Workspace' }));

    expect(onSelect).toHaveBeenCalledWith('workspace');
    expect(screen.getByRole('button', { name: 'Tools' })).toHaveAttribute(
      'aria-expanded',
      'false',
    );
  });
});
