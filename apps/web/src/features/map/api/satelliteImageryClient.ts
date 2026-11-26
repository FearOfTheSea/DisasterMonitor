import type { SatelliteSourceId } from '@/features/map/model/satelliteImagery';
import { sourceById } from '@/features/map/model/satelliteImagery';
import {
  matchesApiSchema,
  type SatelliteAvailabilityResponse,
} from '@/shared/api/generated/assistant';
import { API_BASE_URL } from '@/shared/config/runtime';

export type SatelliteTemporalAvailability = {
  sourceId: SatelliteSourceId;
  availabilityState: 'available' | 'empty' | 'degraded' | 'error';
  defaultTime?: string;
  timeValues: string[];
  metadataRetrievedAt?: string;
  limitations: string[];
};

export async function fetchSatelliteTemporalAvailability(
  signal?: AbortSignal,
): Promise<SatelliteTemporalAvailability[]> {
  const response = await fetch(`${API_BASE_URL}/satellite-imagery/availability`, {
    signal,
  });
  if (!response.ok)
    throw new Error(`Satellite availability failed with status ${response.status}.`);
  const body = await response.json();
  if (!matchesApiSchema('SatelliteAvailabilityResponse', body))
    throw new Error('Satellite temporal availability returned an invalid response.');
  return (body as SatelliteAvailabilityResponse).products.map((item) => ({
    sourceId: sourceById(item.source_id).id,
    availabilityState: item.state,
    defaultTime: item.default_time ?? undefined,
    timeValues: item.time_values,
    metadataRetrievedAt: item.metadata_retrieved_at ?? undefined,
    limitations: item.limitations ?? [],
  }));
}
