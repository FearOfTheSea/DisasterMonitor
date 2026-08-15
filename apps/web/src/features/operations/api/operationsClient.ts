import { API_BASE_URL } from '@/shared/config/runtime';
import type {
  EvidenceSnapshot,
  OperatorReviewResult,
  ProviderFreshness,
} from '@/shared/types/operations';

async function responseJson<T>(response: Response): Promise<T> {
  if (!response.ok) {
    let detail = `Request failed with status ${response.status}.`;
    try {
      const body = (await response.json()) as { detail?: string };
      if (body.detail) detail = body.detail;
    } catch {
      // The stable status remains useful when an intermediary returns non-JSON.
    }
    throw new Error(detail);
  }
  return (await response.json()) as T;
}

export async function fetchProviderFreshness(signal?: AbortSignal) {
  const response = await fetch(`${API_BASE_URL}/operations/providers`, { signal });
  return responseJson<ProviderFreshness[]>(response);
}

export async function fetchEvidenceHistory(signal?: AbortSignal) {
  const response = await fetch(`${API_BASE_URL}/operations/evidence-history?limit=25`, {
    signal,
  });
  return responseJson<EvidenceSnapshot[]>(response);
}

export async function recordOperatorReview(stateVersion: string, rationale: string) {
  const response = await fetch(`${API_BASE_URL}/operations/operator-actions`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      state_version: stateVersion,
      decision: 'reviewed',
      rationale,
      policy_ids: ['human-review-v1'],
    }),
  });
  return responseJson<OperatorReviewResult>(response);
}
