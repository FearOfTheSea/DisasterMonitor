import { describe, expect, it } from 'vitest';

import {
  applyRegionalPreset,
  REGIONAL_PRESETS,
  regionalPresetAfterViewChange,
} from '@/features/map/model/regionalPresets';

describe('regional navigation presets', () => {
  it('defines the exact presentation-only navigation set', () => {
    expect(REGIONAL_PRESETS.map((preset) => preset.label)).toEqual([
      'Global',
      'Americas',
      'Europe',
      'Africa',
      'MENA',
      'South Asia',
      'East Asia',
      'Southeast Asia',
      'Oceania',
    ]);
    expect(REGIONAL_PRESETS.every((preset) => preset.bounds.length === 4)).toBe(true);
  });

  it('selects a stable view and clears the preset after manual movement', () => {
    const selected = applyRegionalPreset('europe');
    expect(selected.regionalPreset).toBe('europe');
    expect(regionalPresetAfterViewChange('europe', selected.view)).toBe('europe');
    expect(
      regionalPresetAfterViewChange('europe', {
        ...selected.view,
        centerLongitude: selected.view.centerLongitude + 3,
      }),
    ).toBe('custom');
  });
});
