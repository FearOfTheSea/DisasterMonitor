'use client';

import { FormEvent, useCallback, useEffect, useState } from 'react';

import {
  addAnalystNote,
  addBookmark,
  createRunbook,
  fetchOperatorWorkspace,
} from '@/features/operations/api/operatorWorkspaceClient';
import type { OperatorWorkspaceState } from '@/shared/types/operatorWorkspace';

type OperatorWorkspaceProps = {
  selectedIncidentId?: string;
  section?: 'workspace' | 'bookmarks' | 'all';
};

export function OperatorWorkspace({
  selectedIncidentId,
  section = 'all',
}: OperatorWorkspaceProps) {
  const [workspace, setWorkspace] = useState<OperatorWorkspaceState | null>(null);
  const [note, setNote] = useState('');
  const [tags, setTags] = useState('');
  const [bookmarkId, setBookmarkId] = useState('');
  const [bookmarkLabel, setBookmarkLabel] = useState('');
  const [runbookName, setRunbookName] = useState('');
  const [runbookSteps, setRunbookSteps] = useState('');
  const [status, setStatus] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(
    async (signal?: AbortSignal) => {
      try {
        setWorkspace(await fetchOperatorWorkspace(selectedIncidentId, signal));
        setError(null);
      } catch (caught) {
        if (!(caught instanceof DOMException && caught.name === 'AbortError')) {
          setError(
            caught instanceof Error ? caught.message : 'Workspace failed to load.',
          );
        }
      }
    },
    [selectedIncidentId],
  );

  useEffect(() => {
    const controller = new AbortController();
    const timer = window.setTimeout(() => void refresh(controller.signal), 0);
    return () => {
      window.clearTimeout(timer);
      controller.abort();
    };
  }, [refresh]);

  async function saveNote(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    await runMutation(async () => {
      await addAnalystNote({
        incident_id: selectedIncidentId ?? null,
        text: note.trim(),
        tags: tags
          .split(',')
          .map((tag) => tag.trim())
          .filter(Boolean),
      });
      setNote('');
      setTags('');
    }, 'Non-evidence note saved.');
  }

  async function saveBookmark(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    await runMutation(async () => {
      await addBookmark({
        incident_id: selectedIncidentId ?? null,
        target_type: 'evidence_reference',
        target_id: bookmarkId.trim(),
        label: bookmarkLabel.trim(),
      });
      setBookmarkId('');
      setBookmarkLabel('');
    }, 'Bookmark saved as non-evidence.');
  }

  async function saveRunbook(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    await runMutation(async () => {
      await createRunbook({
        name: runbookName.trim(),
        steps: runbookSteps
          .split('\n')
          .map((step) => step.trim())
          .filter(Boolean),
      });
      setRunbookName('');
      setRunbookSteps('');
    }, 'Checklist template saved without autonomous actions.');
  }

  async function runMutation(action: () => Promise<void>, success: string) {
    try {
      setError(null);
      await action();
      setStatus(success);
      await refresh();
    } catch (caught) {
      setStatus(null);
      setError(caught instanceof Error ? caught.message : 'Workspace update failed.');
    }
  }

  return (
    <section className="operations-section operator-workspace">
      <div className="operations-heading">
        <div>
          <h3>{section === 'bookmarks' ? 'Bookmarks' : 'Operator workspace'}</h3>
          <p>Notes, tags, bookmarks, and checklists never enter canonical evidence.</p>
        </div>
        <span className="non-evidence-badge">Non-evidence operator state</span>
      </div>
      <details>
        <summary>
          {section === 'bookmarks'
            ? 'Add bookmark'
            : section === 'workspace'
              ? 'Add note or checklist'
              : 'Add note, bookmark, or checklist'}
        </summary>
        <div className="operator-workspace-forms">
          {section !== 'bookmarks' && (
            <form onSubmit={saveNote}>
              <strong>Analyst note</strong>
              <textarea
                aria-label="Analyst note"
                maxLength={10_000}
                rows={2}
                required
                value={note}
                onChange={(event) => setNote(event.target.value)}
              />
              <input
                aria-label="Note tags"
                placeholder="Tags, comma separated"
                value={tags}
                onChange={(event) => setTags(event.target.value)}
              />
              <button type="submit" disabled={!note.trim()}>
                Save non-evidence note
              </button>
            </form>
          )}
          {section !== 'workspace' && (
            <form onSubmit={saveBookmark}>
              <strong>Evidence bookmark</strong>
              <input
                aria-label="Bookmark target ID"
                placeholder="Evidence, finding, or source ID"
                required
                value={bookmarkId}
                onChange={(event) => setBookmarkId(event.target.value)}
              />
              <input
                aria-label="Bookmark label"
                placeholder="Label"
                required
                value={bookmarkLabel}
                onChange={(event) => setBookmarkLabel(event.target.value)}
              />
              <button
                type="submit"
                disabled={!bookmarkId.trim() || !bookmarkLabel.trim()}
              >
                Save non-evidence bookmark
              </button>
            </form>
          )}
          {section !== 'bookmarks' && (
            <form onSubmit={saveRunbook}>
              <strong>Checklist template</strong>
              <input
                aria-label="Checklist name"
                placeholder="Checklist name"
                required
                value={runbookName}
                onChange={(event) => setRunbookName(event.target.value)}
              />
              <textarea
                aria-label="Checklist steps"
                placeholder="One step per line; evidence IDs may be referenced"
                rows={3}
                required
                value={runbookSteps}
                onChange={(event) => setRunbookSteps(event.target.value)}
              />
              <button
                type="submit"
                disabled={!runbookName.trim() || !runbookSteps.trim()}
              >
                Save non-autonomous checklist
              </button>
            </form>
          )}
        </div>
      </details>
      <div className="operator-workspace-list">
        {section !== 'bookmarks' &&
          workspace?.notes.map((item) => (
            <article key={item.note_id}>
              <p>{item.text}</p>
              <small>{item.tags.join(' · ') || 'No tags'} · non-evidence</small>
            </article>
          ))}
        {section !== 'workspace' &&
          workspace?.bookmarks.map((item) => (
            <article key={item.bookmark_id}>
              <strong>{item.label}</strong>
              <small>{item.target_id} · non-evidence</small>
            </article>
          ))}
        {section !== 'bookmarks' &&
          workspace?.runbooks.map((item) => (
            <article key={item.template_id}>
              <strong>{item.name}</strong>
              <small>{item.steps.length} manual steps · no autonomous actions</small>
            </article>
          ))}
      </div>
      {status && <p role="status">{status}</p>}
      {error && <p role="alert">{error}</p>}
    </section>
  );
}
