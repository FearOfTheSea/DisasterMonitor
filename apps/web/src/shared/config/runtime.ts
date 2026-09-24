export const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? 'http://localhost:8001/api/v1';

export const DEFAULT_MAP_VIEW = {
  centerLatitude: 10,
  centerLongitude: 0,
  zoom: 1.5,
};
