import { expect, it } from 'vitest';
import { DEFAULT_MAP_VIEW } from '@/features/map/model/mapView';
import { DEFAULT_MAP_VIEW as workspaceDefault } from '@/shared/config/runtime';

it('opens a regional overview instead of a street-level map with a consistent default', () => {
  expect(DEFAULT_MAP_VIEW.zoom).toBeLessThanOrEqual(5);
  expect(DEFAULT_MAP_VIEW).toEqual(workspaceDefault);
});
