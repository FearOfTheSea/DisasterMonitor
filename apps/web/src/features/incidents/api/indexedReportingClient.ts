import { matchesApiSchema } from '@/shared/api/generated/assistant';
import type { IndexedReportingResponse } from '@/shared/api/generated/assistant';
import { readJsonResponse } from '@/shared/api/http';
import { API_BASE_URL } from '@/shared/config/runtime';

export async function fetchIndexedReporting(
  scanId: string,
  query: string,
  cursor: string | null,
  snapshot: string | null,
  signal?: AbortSignal,
): Promise<IndexedReportingResponse> {
  const selection = query.trim();
  const params = new URLSearchParams({ query: selection });
  if (cursor !== null) params.set('cursor', cursor);
  const response = await fetch(
    `${API_BASE_URL}/discovery-scans/${encodeURIComponent(scanId)}/indexed-reporting?${params}`,
    { signal },
  );
  const body = await readJsonResponse<unknown>(response);
  if (!matchesApiSchema('IndexedReportingResponse', body))
    throw new Error('Received invalid indexed reporting.');
  const page = body as IndexedReportingResponse;
  if (
    page.query !== selection ||
    !page.snapshot ||
    (snapshot !== null && page.snapshot !== snapshot) ||
    page.items.length > 25 ||
    new Set(page.items.map((item) => item.observation_id)).size !== page.items.length ||
    (page.next_cursor !== null &&
      (!page.items.length || !page.next_cursor || page.next_cursor === cursor)) ||
    page.items.some((item) => {
      const dates = [
        item.observed_at,
        item.published_at,
        item.updated_at,
        item.indexed_at,
      ];
      try {
        const url = new URL(item.canonical_url);
        return (
          url.protocol !== 'https:' ||
          Boolean(url.username || url.password) ||
          !item.observation_id ||
          !item.provider ||
          dates.some((value) => value !== null && !Number.isFinite(Date.parse(value)))
        );
      } catch {
        return true;
      }
    })
  )
    throw new Error('Received invalid indexed reporting continuation.');
  return page;
}
