import type { SourceCatalogSnapshot } from '@/features/sources/model/sourceCatalog';
import { matchesApiSchema } from '@/shared/api/generated/assistant';
import { API_BASE_URL } from '@/shared/config/runtime';

export async function fetchSourceCatalog(
  signal?: AbortSignal,
): Promise<SourceCatalogSnapshot> {
  const response = await fetch(`${API_BASE_URL}/sources`, { signal });
  if (!response.ok) {
    throw new Error(`Source Catalog request failed with status ${response.status}.`);
  }
  const body = (await response.json()) as unknown;
  if (!matchesApiSchema('SourceCatalogResponse', body)) {
    throw new Error('Source Catalog returned an invalid response.');
  }
  return body as SourceCatalogSnapshot;
}
