import { matchesApiSchema } from '@/shared/api/generated/assistant';
import type {
  CollectedReportingResponse,
  RetainedReportingPageResponse,
} from '@/shared/api/generated/assistant';
import { readJsonResponse } from '@/shared/api/http';
import { API_BASE_URL } from '@/shared/config/runtime';
import { validateRetainedReporting } from './retainedReportingValidation';

export async function fetchCollectedReporting(
  scanId: string,
  offset: number,
  version: string | null,
  unlinkedOnly: boolean,
  signal?: AbortSignal,
): Promise<CollectedReportingResponse> {
  const query = new URLSearchParams({
    offset: String(offset),
    unlinked_only: String(unlinkedOnly),
  });
  if (version !== null) query.set('version', version);
  const response = await fetch(
    `${API_BASE_URL}/discovery-scans/${encodeURIComponent(scanId)}/reporting?${query}`,
    { signal },
  );
  const body = await readJsonResponse<unknown>(response);
  if (!matchesApiSchema('CollectedReportingResponse', body))
    throw new Error('Received invalid collected reporting.');
  const page = body as CollectedReportingResponse;
  const end = offset + page.items.length;
  if (
    page.offset !== offset ||
    page.unlinked_only !== unlinkedOnly ||
    !/^[a-f0-9]{64}$/.test(page.version) ||
    (version !== null && page.version !== version) ||
    page.items.length > 25 ||
    end > page.total ||
    new Set(page.items.map((item) => item.capture_id)).size !== page.items.length ||
    (page.next_offset === null
      ? end !== page.total
      : page.next_offset !== end || end <= offset || end >= page.total)
  )
    throw new Error('Received invalid collected reporting continuation.');
  return page;
}

export async function fetchCollectedReportingText(
  scanId: string,
  captureId: string,
  offset: number,
  signal?: AbortSignal,
): Promise<RetainedReportingPageResponse> {
  const response = await fetch(
    `${API_BASE_URL}/discovery-scans/${encodeURIComponent(scanId)}/reporting/${encodeURIComponent(captureId)}?offset=${offset}`,
    { signal },
  );
  return validateRetainedReporting(
    await readJsonResponse<unknown>(response),
    captureId,
    offset,
  );
}
