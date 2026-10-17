import { readJsonResponse } from '@/shared/api/http';
import { API_BASE_URL } from '@/shared/config/runtime';
import type {
  AnalystNote,
  OperatorBookmark,
  OperatorWorkspaceState,
  RunbookTemplate,
  CaseNotebook,
  NotebookEntry,
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

export async function createNotebook(body: {
  title: string;
  created_by: string;
  incident_ids: string[];
}) {
  return post<CaseNotebook>('/operator-workspace/notebooks', body);
}
export async function addNotebookEntry(
  notebookId: string,
  body: Omit<
    NotebookEntry,
    'entry_id' | 'notebook_id' | 'created_at' | 'evidence' | 'alters_canonical_state'
  >,
) {
  return post<NotebookEntry>(
    `/operator-workspace/notebooks/${encodeURIComponent(notebookId)}/entries`,
    body,
  );
}
export async function fetchNotebookEntries(notebookId: string, signal?: AbortSignal) {
  const response = await fetch(
    `${API_BASE_URL}/operator-workspace/notebooks/${encodeURIComponent(notebookId)}/entries`,
    { signal },
  );
  return readJsonResponse<NotebookEntry[]>(response);
}

async function post<Result>(path: string, body: object) {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  return readJsonResponse<Result>(response);
}
