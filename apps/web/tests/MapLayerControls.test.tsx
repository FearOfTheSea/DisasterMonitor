import { cleanup, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { createDefaultMapLayerState } from '@/features/map/model/mapLayerState';
import { MapLayerControls } from '@/features/map/ui/MapLayerControls';

afterEach(cleanup);

describe('MapLayerControls', () => {
  it('applies presets, time windows, individual visibility, and layer explanations', async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    const state = createDefaultMapLayerState();
    const { rerender } = render(<MapLayerControls state={state} onChange={onChange} />);

    await user.click(screen.getByRole('button', { name: 'Layers' }));
    await user.click(screen.getByRole('button', { name: 'Satellite preset' }));
    expect(onChange).toHaveBeenCalledWith(
      expect.objectContaining({
        activePreset: 'satellite',
        visibility: expect.objectContaining({
          'active-incidents': true,
          'satellite-imagery': true,
          'cop-evidence': false,
        }),
      }),
    );

    await user.click(screen.getByRole('radio', { name: '1h' }));
    expect(onChange).toHaveBeenCalledWith({ ...state, timeWindow: '1h' });

    await user.click(screen.getByRole('checkbox', { name: 'Satellite imagery' }));
    expect(onChange).toHaveBeenCalledWith(
      expect.objectContaining({
        activePreset: undefined,
        visibility: expect.objectContaining({ 'satellite-imagery': true }),
      }),
    );

    await user.click(screen.getByRole('button', { name: 'About Satellite imagery' }));
    const explanation = screen.getByRole('dialog', {
      name: 'About Satellite imagery',
    });
    expect(explanation).toHaveTextContent('Source / authority');
    expect(explanation).toHaveTextContent('Freshness meaning');
    expect(explanation).toHaveTextContent('Confidence / status meaning');
    expect(explanation).toHaveTextContent(/not live/i);

    rerender(
      <MapLayerControls
        state={{
          ...state,
          visibility: { ...state.visibility, 'satellite-imagery': true },
        }}
        onChange={onChange}
      >
        <div>Integrated satellite source controls</div>
      </MapLayerControls>,
    );
    expect(screen.getByText('Integrated satellite source controls')).toBeVisible();
  });
});

it('lets the user reveal and dismiss layer controls without changing map state', async () => {
  const user = userEvent.setup();
  const onChange = vi.fn();
  render(<MapLayerControls state={createDefaultMapLayerState()} onChange={onChange} />);
  const toggle = screen.getByRole('button', { name: 'Layers' });
  expect(toggle).toHaveAttribute('aria-expanded', 'false');
  expect(
    screen.queryByRole('button', { name: 'Satellite preset' }),
  ).not.toBeInTheDocument();
  await user.click(toggle);
  expect(screen.getByRole('button', { name: 'Satellite preset' })).toBeVisible();
  await user.click(toggle);
  expect(toggle).toHaveAttribute('aria-expanded', 'false');
  expect(onChange).not.toHaveBeenCalled();
});
