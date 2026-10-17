import { API_BASE_URL } from '@/shared/config/runtime';
import { readJsonResponse } from '@/shared/api/http';
import {
  matchesApiSchema,
  type StandaloneEvidenceResult,
} from '@/shared/api/generated/assistant';
export type EvidenceSection = StandaloneEvidenceResult['section'];

export async function fetchSectionEvidence(
  identifier: string,
  section: EvidenceSection,
  signal?: AbortSignal,
): Promise<StandaloneEvidenceResult> {
  const response = await fetch(
    `${API_BASE_URL}/incidents/${encodeURIComponent(identifier)}/evidence/${section}`,
    { signal },
  );
  const body = await readJsonResponse<unknown>(response);
  if (!matchesApiSchema('SectionEvidenceResponse', body))
    throw new Error('Evidence returned an invalid response.');
  return (body as { evidence: StandaloneEvidenceResult }).evidence;
}

export async function fetchInspectionExposure(
  identifier: string,
  bounds: [number, number, number, number],
): Promise<StandaloneEvidenceResult> {
  const response = await fetch(
    `${API_BASE_URL}/incidents/${encodeURIComponent(identifier)}/evidence/exposure/inspection`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ bounds }),
    },
  );
  const body = await readJsonResponse<unknown>(response);
  if (!matchesApiSchema('SectionEvidenceResponse', body))
    throw new Error('Exposure returned an invalid response.');
  return (body as { evidence: StandaloneEvidenceResult }).evidence;
}
