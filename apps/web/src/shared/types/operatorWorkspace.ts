export type AnalystNote = {
  note_id: string;
  incident_id: string | null;
  text: string;
  tags: string[];
  created_at: string;
  evidence: false;
};

export type OperatorBookmark = {
  bookmark_id: string;
  incident_id: string | null;
  target_type: string;
  target_id: string;
  label: string;
  created_at: string;
  evidence: false;
};

export type RunbookTemplate = {
  template_id: string;
  name: string;
  steps: string[];
  created_at: string;
  autonomous_actions: false;
};

export type OperatorWorkspaceState = {
  boundary: 'non_evidence_operator_state';
  incident_id: string | null;
  notes: AnalystNote[];
  bookmarks: OperatorBookmark[];
  runbooks: RunbookTemplate[];
  notebooks?: CaseNotebook[];
};

export type CaseNotebook = {
  notebook_id: string;
  title: string;
  created_by: string;
  created_at: string;
  incident_ids: string[];
  evidence: false;
};
export type NotebookEntry = {
  entry_id: string;
  notebook_id: string;
  kind: 'source_snapshot' | 'question' | 'analytical_run' | 'conclusion';
  title: string;
  content: string;
  reference_id: string | null;
  created_by: string;
  created_at: string;
  evidence: false;
  alters_canonical_state: false;
};
