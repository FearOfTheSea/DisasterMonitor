import { cleanup, render, screen, fireEvent } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { DiscoveryScanControls } from '@/features/incidents/ui/DiscoveryScanControls';
import type { DiscoveryScanResponse } from '@/shared/api/generated/assistant';
afterEach(cleanup);

describe('publication scan controls', () => {
  it('offers all five periods with seven days provisional default and starts a scan', () => {
    const start = vi.fn();
    render(<DiscoveryScanControls days={7} onDaysChange={vi.fn()} onScan={start} />);
    expect(screen.getByRole('combobox', { name: 'Reporting period' })).toHaveValue('7');
    expect(screen.getAllByRole('option')).toHaveLength(5);
    expect(screen.getByText(/may take a while/i)).toBeVisible();
    fireEvent.click(screen.getByRole('button', { name: 'Scan the world' }));
    expect(start).toHaveBeenCalledOnce();
  });

  it.each([
    ['running', 0, 'Scanning the world'],
    ['completed', 0, 'No matching events were found in this scan'],
    ['completed', 1, 'Scan completed'],
    ['incomplete', 1, 'Scan incomplete'],
    ['failed', 0, 'Scan failed'],
  ])('shows %s without claiming exhaustive coverage', (status, count, text) => {
    const run = {
      status,
      scan_id: 'test',
      interval_start: '2026-10-10T12:00:00Z',
      interval_end: '2026-10-17T12:00:00Z',
      issues: ['Fixture provider limit'],
      unlocated_count: 1,
      coverage_notice:
        'Completion describes this scan process; coverage is not exhaustive.',
      snapshot: { incidents: Array(count).fill({}) },
    } as DiscoveryScanResponse;
    render(
      <DiscoveryScanControls
        days={7}
        onDaysChange={vi.fn()}
        onScan={vi.fn()}
        run={run}
      />,
    );
    expect(screen.getByText(text, { exact: false })).toBeVisible();
    expect(screen.getByText(/not exhaustive/i)).toBeVisible();
    expect(screen.getByText(/remains? accessible in the list/i)).toBeVisible();
    fireEvent.click(screen.getByText('Acquisition limits and notices'));
    expect(screen.getByText('Fixture provider limit')).toBeVisible();
  });
});
