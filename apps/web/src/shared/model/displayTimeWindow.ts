export const MAP_TIME_WINDOWS = ['1h', '6h', '24h', '48h', '7d'] as const;
export type MapTimeWindow = (typeof MAP_TIME_WINDOWS)[number];

export const WINDOW_MILLISECONDS: Record<MapTimeWindow, number> = {
  '1h': 60 * 60 * 1_000,
  '6h': 6 * 60 * 60 * 1_000,
  '24h': 24 * 60 * 60 * 1_000,
  '48h': 48 * 60 * 60 * 1_000,
  '7d': 7 * 24 * 60 * 60 * 1_000,
};
