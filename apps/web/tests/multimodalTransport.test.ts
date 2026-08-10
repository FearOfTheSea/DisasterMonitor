import { describe, expect, it } from 'vitest';

import {
  copMatchesMultimodalState,
  isCommonOperationalPicture,
  isMultimodalEvidenceState,
} from '@/shared/validation/multimodal';
import { commonOperationalPicture, multimodalState } from './fixtures/multimodal';

function clone<T>(value: T): T {
  return JSON.parse(JSON.stringify(value)) as T;
}

describe('multimodal transport validation', () => {
  it('accepts complete analytical lineage and matching state versions', () => {
    expect(isMultimodalEvidenceState(multimodalState)).toBe(true);
    expect(isCommonOperationalPicture(commonOperationalPicture)).toBe(true);
    expect(copMatchesMultimodalState(commonOperationalPicture, multimodalState)).toBe(
      true,
    );
  });

  it('rejects analytical geometry impersonating source authority', () => {
    const unsafe = clone(commonOperationalPicture) as unknown as {
      layers: { features: { authority: string }[] }[];
    };
    unsafe.layers[0].features[0].authority = 'official_source';

    expect(isCommonOperationalPicture(unsafe)).toBe(false);
  });

  it('rejects missing provenance and hidden uncertainty', () => {
    const noProvenance = clone(commonOperationalPicture);
    noProvenance.layers[0].features[0].source_asset_ids = [];
    expect(isCommonOperationalPicture(noProvenance)).toBe(false);

    const hiddenStatus = clone(commonOperationalPicture);
    hiddenStatus.layers[0].features[0].uncertainty = '';
    expect(isCommonOperationalPicture(hiddenStatus)).toBe(false);
  });

  it('rejects geometry outside WGS84 and mismatched EW lineage', () => {
    const invalidGeometry = clone(commonOperationalPicture) as unknown as {
      layers: { features: { geometry: { coordinates: number[][][] } }[] }[];
    };
    invalidGeometry.layers[0].features[0].geometry.coordinates[0][0][0] = 220;
    expect(isCommonOperationalPicture(invalidGeometry)).toBe(false);

    const stale = clone(commonOperationalPicture);
    stale.multimodal_state_version = 'multimodal-state:other';
    expect(copMatchesMultimodalState(stale, multimodalState)).toBe(false);
  });

  it('rejects a closed but self-intersecting renderer polygon', () => {
    const unsafe = clone(commonOperationalPicture);
    unsafe.layers[0].features[0].geometry = {
      type: 'Polygon',
      crs: 'EPSG:4326',
      coordinates: [
        [
          [136.8, 34.8],
          [137.2, 35.2],
          [136.8, 35.2],
          [137.2, 34.8],
          [136.8, 34.8],
        ],
      ],
    };

    expect(isCommonOperationalPicture(unsafe)).toBe(false);
  });
});
