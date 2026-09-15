import { readJsonResponse } from '@/shared/api/http';
import { API_BASE_URL } from '@/shared/config/runtime';
import type {
  AnalystNote,
  OperatorBookmark,
  OperatorWorkspaceState,
  RunbookTemplate,
} from '@/shared/types/operatorWorkspace';

export async function fetchOperatorWorkspace(
  incidentId?: string,
  signal?: AbortSignal,
) {
  const query = incidentId ? `?incident_id=${encodeURIComponent(incidentId)}` : '';
  const response = await fetch(`${API_BASE_URL}/operator-workspace${query}`, {
    signal,
  });
  return readJsonResponse<OperatorWorkspaceState>(response);
}

export async function addAnalystNote(body: {
  incident_id: string | null;
  text: string;
  tags: string[];
}) {
  return post<AnalystNote>('/operator-workspace/notes', body);
}

export async function addBookmark(body: {
  incident_id: string | null;
  target_type: string;
  target_id: string;
  label: string;
}) {
  return post<OperatorBookmark>('/operator-workspace/bookmarks', body);
}

export async function createRunbook(body: { name: string; steps: string[] }) {
  return post<RunbookTemplate>('/operator-workspace/runbooks', body);
}

async function post<Result>(path: string, body: object) {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  return readJsonResponse<Result>(response);
}
