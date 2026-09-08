import type { ActiveIncidentsSnapshot } from '@/features/incidents/model/activeIncidents';
import type { DisasterType } from '@/features/incidents/model/activeIncidents';
import { API_BASE_URL } from '@/shared/config/runtime';
import { readJsonResponse } from '@/shared/api/http';

type ActiveIncidentsRequest = {
  timeWindowDays?: number;
  limitPerDisaster?: number;
  view?: 'recent' | 'ongoing' | 'recently_updated' | 'historical';
  hazard?: DisasterType;
  country?: string;
  search?: string;
  pageSize?: number;
  cursor?: string;
  signal?: AbortSignal;
};

export async function fetchActiveIncidents({
  timeWindowDays = 7,
  limitPerDisaster = 10,
  view,
  hazard,
  country,
  search,
  pageSize,
  cursor,
  signal,
}: ActiveIncidentsRequest = {}): Promise<ActiveIncidentsSnapshot> {
  const parameters = new URLSearchParams({
    time_window_days: String(timeWindowDays),
    limit_per_disaster: String(limitPerDisaster),
  });
  if (view) parameters.set('view', view);
  if (hazard) parameters.set('hazard', hazard);
  if (country?.trim()) parameters.set('country', country.trim().toUpperCase());
  if (search?.trim()) parameters.set('search', search.trim());
  if (pageSize !== undefined) parameters.set('page_size', String(pageSize));
  if (cursor) parameters.set('cursor', cursor);
  const response = await fetch(`${API_BASE_URL}/incidents?${parameters}`, { signal });
  const body = await readJsonResponse<ActiveIncidentsSnapshot>(
    response,
    `Active Incidents request failed with status ${response.status}.`,
  );
  return {
    ...body,
    correlations: (body.correlations ?? []).map((correlation) => ({
      ...correlation,
      source_ids: correlation.source_ids ?? [],
    })),
  };
}
