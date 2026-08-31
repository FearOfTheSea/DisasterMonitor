import type { ActiveIncidentsSnapshot } from '@/features/incidents/model/activeIncidents';
import { API_BASE_URL } from '@/shared/config/runtime';

type ActiveIncidentsRequest = {
  timeWindowDays?: number;
  limitPerDisaster?: number;
  signal?: AbortSignal;
};

export async function fetchActiveIncidents({
  timeWindowDays = 7,
  limitPerDisaster = 10,
  signal,
}: ActiveIncidentsRequest = {}): Promise<ActiveIncidentsSnapshot> {
  const parameters = new URLSearchParams({
    time_window_days: String(timeWindowDays),
    limit_per_disaster: String(limitPerDisaster),
  });
  const response = await fetch(`${API_BASE_URL}/incidents?${parameters}`, { signal });
  if (!response.ok) {
    let detail = `Active Incidents request failed with status ${response.status}.`;
    try {
      const body = (await response.json()) as { detail?: string };
      if (body.detail) detail = body.detail;
    } catch {
      // Keep the stable HTTP status when an intermediary returns non-JSON.
    }
    throw new Error(detail);
  }
  const body = (await response.json()) as ActiveIncidentsSnapshot;
  return {
    ...body,
    correlations: (body.correlations ?? []).map((correlation) => ({
      ...correlation,
      source_ids: correlation.source_ids ?? [],
    })),
  };
}
