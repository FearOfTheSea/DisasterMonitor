import { API_BASE_URL } from '@/shared/config/runtime';
import type {
  CountryCatalogStatus,
  EvidenceSnapshot,
  OperatorReviewResult,
  ProviderFreshness,
} from '@/shared/types/operations';
import { readJsonResponse } from '@/shared/api/http';

export async function fetchProviderFreshness(signal?: AbortSignal) {
  const response = await fetch(`${API_BASE_URL}/operations/providers`, { signal });
  return readJsonResponse<ProviderFreshness[]>(response);
}

export async function fetchEvidenceHistory(signal?: AbortSignal) {
  const response = await fetch(`${API_BASE_URL}/operations/evidence-history?limit=25`, {
    signal,
  });
  return readJsonResponse<EvidenceSnapshot[]>(response);
}

export async function fetchCountryCatalogStatus(signal?: AbortSignal) {
  const response = await fetch(`${API_BASE_URL}/operations/country-catalog`, {
    signal,
  });
  return readJsonResponse<CountryCatalogStatus>(response);
}

export async function requestCountryCatalogUpdate() {
  const response = await fetch(`${API_BASE_URL}/operations/country-catalog/update`, {
    method: 'POST',
  });
  return readJsonResponse<CountryCatalogStatus>(response);
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
  return readJsonResponse<OperatorReviewResult>(response);
}
