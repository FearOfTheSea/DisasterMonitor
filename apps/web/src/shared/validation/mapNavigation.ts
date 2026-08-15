import type { MapNavigationAction } from '@/shared/types/assistant';

export function isMapNavigationAction(value: unknown): value is MapNavigationAction {
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    return false;
  }
  const action = value as Record<string, unknown>;
  if (
    action.type !== 'fit_bounds' ||
    typeof action.label !== 'string' ||
    action.label.trim().length === 0 ||
    action.label.length > 160 ||
    typeof action.max_zoom !== 'number' ||
    !Number.isFinite(action.max_zoom) ||
    action.max_zoom < 2 ||
    action.max_zoom > 18 ||
    !Array.isArray(action.bounds) ||
    action.bounds.length !== 4 ||
    !action.bounds.every((coordinate) =>
      typeof coordinate === 'number' ? Number.isFinite(coordinate) : false,
    )
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
