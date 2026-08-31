import type {
  IncidentWatch,
  IncidentWatchChange,
  IncidentWatchCreate,
  IncidentWatchReadResult,
} from '@/features/operations/model/incidentWatch';
import { API_BASE_URL } from '@/shared/config/runtime';

async function responseJson<T>(response: Response): Promise<T> {
  if (!response.ok) {
    let detail = `Request failed with status ${response.status}.`;
    try {
      const body = (await response.json()) as { detail?: string };
      if (body.detail) detail = body.detail;
    } catch {
      // Preserve the stable status when an intermediary returns non-JSON.
    }
    throw new Error(detail);
  }
  return (await response.json()) as T;
}

function watchUrl(watchId: string, suffix = ''): string {
  return `${API_BASE_URL}/incident-watches/${encodeURIComponent(watchId)}${suffix}`;
}

export async function fetchIncidentWatches(
  signal?: AbortSignal,
): Promise<IncidentWatch[]> {
  return responseJson<IncidentWatch[]>(
    await fetch(`${API_BASE_URL}/incident-watches`, { signal }),
  );
}

export async function createIncidentWatch(
  request: IncidentWatchCreate,
): Promise<IncidentWatch> {
  return responseJson<IncidentWatch>(
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
  return responseJson<IncidentWatch>(
    await fetch(watchUrl(watchId, '/enabled'), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ enabled }),
    }),
  );
}

export async function deleteIncidentWatch(watchId: string): Promise<void> {
  const response = await fetch(watchUrl(watchId), { method: 'DELETE' });
  if (!response.ok) await responseJson<never>(response);
}

export async function fetchIncidentWatchTimeline(
  watchId: string,
  signal?: AbortSignal,
): Promise<IncidentWatchChange[]> {
  return responseJson<IncidentWatchChange[]>(
    await fetch(watchUrl(watchId, '/timeline'), { signal }),
  );
}

export async function markIncidentWatchTimelineRead(
  watchId: string,
  changeIds: string[],
): Promise<IncidentWatchReadResult> {
  return responseJson<IncidentWatchReadResult>(
    await fetch(watchUrl(watchId, '/timeline/read'), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ change_ids: changeIds }),
    }),
  );
}
