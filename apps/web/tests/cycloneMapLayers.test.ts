import { describe, expect, it } from 'vitest';

import { cycloneStyleSemantics } from '@/features/map/model/cycloneMapLayers';

describe('cyclone map layer semantics', () => {
  it('distinguishes provisional, forecast, uncertainty, and wind without color alone', () => {
    const provisional = cycloneStyleSemantics('provisional_track');
    const forecast = cycloneStyleSemantics('forecast_track');
    const uncertainty = cycloneStyleSemantics('uncertainty_area');
    const wind = cycloneStyleSemantics('wind_radii');

    expect(provisional.patternLabel).toBe('solid');
    expect(provisional.lineDash).toBeUndefined();
    expect(forecast.patternLabel).toBe('dashed');
    expect(forecast.lineDash).not.toEqual(provisional.lineDash);
    expect(uncertainty.patternLabel).toBe('area-dashed');
    expect(uncertainty.fillColor).not.toBe('transparent');
    expect(wind.patternLabel).toBe('dotted');
    expect(wind.lineDash).not.toEqual(uncertainty.lineDash);
  });
});
