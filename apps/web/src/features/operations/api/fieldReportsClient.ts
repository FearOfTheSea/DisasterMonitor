import { readJsonResponse } from '@/shared/api/http';
import { API_BASE_URL } from '@/shared/config/runtime';
import type {
  FieldReport,
  FieldReportDuplicateCandidate,
  FieldReportReviewOutcome,
  FieldReportReviewRequest,
  NewFieldReportRequest,
} from '@/shared/types/fieldReports';

export async function fetchFieldReports(signal?: AbortSignal) {
  const response = await fetch(
    `${API_BASE_URL}/field-reports?review_state=pending_review&limit=100`,
    { signal },
  );
  return readJsonResponse<FieldReport[]>(response);
}

export async function fetchDuplicateCandidates(signal?: AbortSignal) {
  const response = await fetch(`${API_BASE_URL}/field-reports/duplicate-candidates`, {
    signal,
  });
  return readJsonResponse<FieldReportDuplicateCandidate[]>(response);
}

export async function createFieldReport(body: NewFieldReportRequest) {
  const response = await fetch(`${API_BASE_URL}/field-reports`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  return readJsonResponse<FieldReport>(response);
}

export async function reviewFieldReport(
  reportId: string,
  body: FieldReportReviewRequest,
) {
  const response = await fetch(`${API_BASE_URL}/field-reports/${reportId}/reviews`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  return readJsonResponse<FieldReportReviewOutcome>(response);
}
