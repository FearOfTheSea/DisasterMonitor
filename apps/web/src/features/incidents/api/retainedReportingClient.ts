import { validateRetainedReporting } from './retainedReportingValidation';
import type { RetainedReportingPageResponse } from '@/shared/api/generated/assistant';
import { readJsonResponse } from '@/shared/api/http';
import { API_BASE_URL } from '@/shared/config/runtime';

export async function fetchRetainedReporting(
  incidentId: string,
  captureId: string,
  offset: number,
  signal?: AbortSignal,
): Promise<RetainedReportingPageResponse> {
  const response = await fetch(
    `${API_BASE_URL}/incidents/${encodeURIComponent(incidentId)}/reporting/${encodeURIComponent(captureId)}?offset=${offset}`,
    { signal },
  );
  const body = await readJsonResponse<unknown>(response);
  return validateRetainedReporting(body, captureId, offset);
}
