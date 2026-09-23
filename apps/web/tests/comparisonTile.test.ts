import { describe, expect, it } from 'vitest';

import { comparisonTile } from '@/features/imagery/model/comparisonTile';

describe('comparisonTile', () => {
  it('uses a detailed tile for a point and a shared tile for an area', () => {
    const point = comparisonTile({ coordinates: [106.1, 21.1] });
    const area = comparisonTile({
      coordinates: [
        [
          [106.1, 21.1],
          [106.3, 21.1],
          [106.3, 21.3],
        ],
      ],
    });
    expect(point.zoom).toBe(12);
    expect(area.zoom).toBeLessThan(point.zoom);
  });

  it('falls back safely when coordinates are missing or invalid', () => {
    expect(comparisonTile(null)).toEqual({ zoom: 0, x: 0, y: 0 });
    expect(comparisonTile({ coordinates: [NaN, 95] })).toEqual({ zoom: 0, x: 0, y: 0 });
  });
});
