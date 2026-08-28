import type { MapNavigationAction } from '@/shared/types/assistant';
import { matchesApiSchema } from '@/shared/api/generated/assistant';

export function isMapNavigationAction(value: unknown): value is MapNavigationAction {
  if (!matchesApiSchema('MapNavigationActionResponse', value)) return false;
  const action = value as MapNavigationAction;
  if (
    action.type !== 'fit_bounds' ||
    !action.bounds.every((coordinate) => Number.isFinite(coordinate))
  ) {
    return false;
  }
  const [minLongitude, minLatitude, maxLongitude, maxLatitude] = action.bounds;
  return (
    minLongitude >= -180 &&
    minLongitude <= 180 &&
    maxLongitude >= minLongitude &&
    maxLongitude - minLongitude <= 360 &&
    minLatitude >= -90 &&
    maxLatitude <= 90 &&
    maxLatitude >= minLatitude
  );
}
