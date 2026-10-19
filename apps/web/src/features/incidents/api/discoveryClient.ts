import type { DiscoveryScanResponse } from '@/shared/api/generated/assistant';
import { matchesApiSchema } from '@/shared/api/generated/assistant';
import { readJsonResponse } from '@/shared/api/http';
import { API_BASE_URL } from '@/shared/config/runtime';

export type ReportingDays = 1 | 3 | 7 | 14 | 30;

export async function requestDiscoveryScan(
  days: ReportingDays,
  signal?: AbortSignal,
): Promise<DiscoveryScanResponse> {
  return readScan(
    await fetch(`${API_BASE_URL}/discovery-scans`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ reporting_days: days }),
      signal,
    }),
  );
}

export async function fetchDiscoveryScan(
  id: string,
  signal?: AbortSignal,
): Promise<DiscoveryScanResponse> {
  return readScan(
    await fetch(`${API_BASE_URL}/discovery-scans/${encodeURIComponent(id)}`, {
      signal,
    }),
  );
}

export async function reprocessDiscoveryScan(
  id: string,
  signal?: AbortSignal,
): Promise<DiscoveryScanResponse> {
  return readScan(
    await fetch(`${API_BASE_URL}/discovery-scans/${encodeURIComponent(id)}/reprocess`, {
      method: 'POST',
      signal,
    }),
  );
}

async function readScan(response: Response): Promise<DiscoveryScanResponse> {
  const body = await readJsonResponse<unknown>(response);
  if (!matchesApiSchema('DiscoveryScanResponse', body))
    throw new Error('Discovery returned an invalid scan response.');
  const run = body as DiscoveryScanResponse;
  if (
    Date.parse(run.interval_end) - Date.parse(run.interval_start) !==
    run.reporting_days * 86_400_000
  ) {
    throw new Error('Discovery returned an invalid reporting interval.');
  }
  return {
    ...run,
    snapshot: {
      ...run.snapshot,
      incidents: run.snapshot.incidents ?? [],
      coverage: run.snapshot.coverage ?? [],
      warnings: run.snapshot.warnings ?? [],
    },
  };
}
