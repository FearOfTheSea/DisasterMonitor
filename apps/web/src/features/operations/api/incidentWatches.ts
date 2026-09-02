import type {
  IncidentWatch,
  IncidentWatchChange,
  IncidentWatchCreate,
  IncidentWatchReadResult,
} from '@/features/operations/model/incidentWatch';
import { API_BASE_URL } from '@/shared/config/runtime';
import { readJsonResponse } from '@/shared/api/http';

function watchUrl(watchId: string, suffix = ''): string {
  return `${API_BASE_URL}/incident-watches/${encodeURIComponent(watchId)}${suffix}`;
}

export async function fetchIncidentWatches(
  signal?: AbortSignal,
): Promise<IncidentWatch[]> {
  return readJsonResponse<IncidentWatch[]>(
    await fetch(`${API_BASE_URL}/incident-watches`, { signal }),
  );
}

export async function createIncidentWatch(
  request: IncidentWatchCreate,
): Promise<IncidentWatch> {
  return readJsonResponse<IncidentWatch>(
    await fetch(`${API_BASE_URL}/incident-watches`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(request),
    }),
  );
}

export async function setIncidentWatchEnabled(
  watchId: string,
  enabled: boolean,
): Promise<IncidentWatch> {
  return readJsonResponse<IncidentWatch>(
    await fetch(watchUrl(watchId, '/enabled'), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ enabled }),
    }),
  );
}

export async function deleteIncidentWatch(watchId: string): Promise<void> {
  const response = await fetch(watchUrl(watchId), { method: 'DELETE' });
  if (!response.ok) await readJsonResponse<never>(response);
}

export async function fetchIncidentWatchTimeline(
  watchId: string,
  signal?: AbortSignal,
): Promise<IncidentWatchChange[]> {
  return readJsonResponse<IncidentWatchChange[]>(
    await fetch(watchUrl(watchId, '/timeline'), { signal }),
  );
}

export async function markIncidentWatchTimelineRead(
  watchId: string,
  changeIds: string[],
): Promise<IncidentWatchReadResult> {
  return readJsonResponse<IncidentWatchReadResult>(
    await fetch(watchUrl(watchId, '/timeline/read'), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ change_ids: changeIds }),
    }),
  );
}
