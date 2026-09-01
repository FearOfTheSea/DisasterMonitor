import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import { CommandPalette } from '@/features/commands/ui/CommandPalette';

describe('CommandPalette', () => {
  it('supports shortcut, deterministic search, keyboard execution, and focus restore', async () => {
    const user = userEvent.setup();
    const execute = vi.fn();
    render(
      <>
        <button type="button">Prior focus</button>
        <CommandPalette
          commands={[
            {
              id: 'region:europe',
              label: 'Focus Europe',
              group: 'Regions',
              keywords: ['europe', 'region'],
              execute,
            },
            {
              id: 'open:sources',
              label: 'Open Source Catalog',
              group: 'Navigation',
              keywords: ['source', 'catalog'],
              execute: vi.fn(),
            },
          ]}
        />
      </>,
    );
    const prior = screen.getByRole('button', { name: 'Prior focus' });
    prior.focus();

    await user.keyboard('{Control>}k{/Control}');
    const dialog = screen.getByRole('dialog', { name: 'Command palette' });
    expect(dialog).toBeVisible();
    const input = screen.getByRole('combobox', { name: 'Search commands' });
    expect(input).toHaveFocus();
    await user.type(input, 'Europe');
    expect(screen.getByRole('option', { name: 'Focus Europe' })).toBeVisible();
    await user.keyboard('{ArrowDown}{Enter}');
    expect(execute).toHaveBeenCalledTimes(1);
    expect(
      screen.queryByRole('dialog', { name: 'Command palette' }),
    ).not.toBeInTheDocument();
    expect(prior).toHaveFocus();

    await user.keyboard('{Meta>}k{/Meta}');
    expect(screen.getByRole('dialog', { name: 'Command palette' })).toBeVisible();
    await user.keyboard('{Escape}');
    expect(
      screen.queryByRole('dialog', { name: 'Command palette' }),
    ).not.toBeInTheDocument();
  });
});
