import { API_BASE_URL } from '@/shared/config/runtime';
import { readJsonResponse } from '@/shared/api/http';
import {
  matchesApiSchema,
  type MonitoringReadinessResponse,
} from '@/shared/api/generated/assistant';

export async function fetchMonitoringReadiness(
  signal?: AbortSignal,
): Promise<MonitoringReadinessResponse> {
  const response = await fetch(`${API_BASE_URL}/operations/monitoring`, { signal });
  const body = await readJsonResponse<unknown>(response);
  if (!matchesApiSchema('MonitoringReadinessResponse', body))
    throw new Error('Monitoring availability could not be verified.');
  return body as MonitoringReadinessResponse;
}
