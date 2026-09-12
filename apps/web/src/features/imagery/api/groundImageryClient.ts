import type {
  ApiSchemaName,
  GroundImageryManifestResponse,
  GroundImageryReadinessResponse,
  GroundImageryRequestResponse,
  GroundImageryPrepareRequest,
  GroundImageryWatchRequest,
} from '@/shared/api/generated/assistant';
import { matchesApiSchema } from '@/shared/api/generated/assistant';
import { readJsonResponse } from '@/shared/api/http';
import { API_BASE_URL } from '@/shared/config/runtime';

export async function createGroundImageryRequest(
  incidentId: string,
  signal?: AbortSignal,
): Promise<GroundImageryRequestResponse> {
  return requestJson<GroundImageryRequestResponse>(
    'GroundImageryRequestResponse',
    `${API_BASE_URL}/ground-imagery/requests`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        incident_id: incidentId,
        reference_time: new Date().toISOString(),
        idempotency_key: `ground-view:${incidentId}`,
      }),
      signal,
    },
  );
}

export async function fetchGroundImageryRequest(
  requestId: string,
  signal?: AbortSignal,
): Promise<GroundImageryRequestResponse> {
  return requestJson<GroundImageryRequestResponse>(
    'GroundImageryRequestResponse',
    requestPath(requestId),
    { signal },
  );
}

export async function fetchGroundImageryReadiness(
  signal?: AbortSignal,
): Promise<GroundImageryReadinessResponse> {
  return requestJson<GroundImageryReadinessResponse>(
    'GroundImageryReadinessResponse',
    `${API_BASE_URL}/ground-imagery/readiness`,
    { signal },
  );
}

export async function refreshGroundImageryRequest(
  requestId: string,
): Promise<GroundImageryRequestResponse> {
  return requestJson<GroundImageryRequestResponse>(
    'GroundImageryRequestResponse',
    requestPath(requestId, '/refresh'),
    { method: 'POST' },
  );
}

export async function setGroundImageryWatch(
  requestId: string,
  enabled: boolean,
): Promise<GroundImageryRequestResponse> {
  const payload: GroundImageryWatchRequest = {
    enabled,
    interval_seconds: enabled ? 21_600 : null,
  };
  return requestJson<GroundImageryRequestResponse>(
    'GroundImageryRequestResponse',
    requestPath(requestId, '/watch'),
    {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    },
  );
}

export async function prepareGroundImagerySelection(
  requestId: string,
  payload: GroundImageryPrepareRequest,
): Promise<GroundImageryRequestResponse> {
  return requestJson<GroundImageryRequestResponse>(
    'GroundImageryRequestResponse',
    requestPath(requestId, '/prepare'),
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    },
  );
}

export async function fetchGroundImageryManifest(
  requestId: string,
  signal?: AbortSignal,
): Promise<GroundImageryManifestResponse> {
  return requestJson<GroundImageryManifestResponse>(
    'GroundImageryManifestResponse',
    requestPath(requestId, '/manifest'),
    { signal },
  );
}

function requestUrl(path: string): string {
  return `${API_BASE_URL}/ground-imagery${path}`;
}

function requestPath(requestId: string, suffix = ''): string {
  return requestUrl(`/requests/${encodeURIComponent(requestId)}${suffix}`);
}

async function requestJson<T>(
  schema: ApiSchemaName,
  url: string,
  init: RequestInit,
): Promise<T> {
  let response: Response;
  try {
    response = await fetch(url, init);
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') throw error;
    throw new Error('The Ground view API could not be reached.');
  }
  const body = await readJsonResponse<unknown>(
    response,
    `Ground view request failed with status ${response.status}.`,
  );
  if (!matchesApiSchema(schema, body)) {
    throw new Error('The Ground view API returned an invalid response.');
  }
  return body as T;
}
