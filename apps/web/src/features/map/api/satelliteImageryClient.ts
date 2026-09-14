import type { SatelliteSourceId } from '@/features/map/model/satelliteImagery';
import { sourceById } from '@/features/map/model/satelliteImagery';
import { API_BASE_URL } from '@/shared/config/runtime';

export type SatelliteSourceAvailability = {
  sourceId: SatelliteSourceId;
  available: boolean;
};

export async function fetchSatelliteImageryCatalog(
  signal?: AbortSignal,
): Promise<SatelliteSourceAvailability[]> {
  const response = await fetch(`${API_BASE_URL}/satellite-imagery`, { signal });
  if (!response.ok) {
    throw new Error(`Satellite imagery request failed with status ${response.status}.`);
  }
  const body = (await response.json()) as unknown;
  if (!isRecord(body) || !Array.isArray(body.products)) {
    throw new Error('Satellite imagery catalog returned an invalid response.');
  }
  return body.products.map((item) => {
    if (!isRecord(item) || typeof item.source_id !== 'string') {
      throw new Error('Satellite imagery catalog returned an invalid product.');
    }
    const source = sourceById(item.source_id);
    if (typeof item.available !== 'boolean') {
      throw new Error(`Satellite imagery availability is invalid for ${source.id}.`);
    }
    return { sourceId: source.id, available: item.available };
  });
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null;
}
