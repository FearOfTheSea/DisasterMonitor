'use client';
import { useEffect, useState, type FormEvent } from 'react';
import {
  createNotebook,
  fetchNotebookEntries,
  addNotebookEntry,
} from '@/features/operations/api/operatorWorkspaceClient';
import type { CaseNotebook, NotebookEntry } from '@/shared/types/operatorWorkspace';

export function NotebookEditor({
  notebooks,
  incidentId,
  onSaved,
}: {
  notebooks: CaseNotebook[];
  incidentId?: string;
  onSaved: () => void;
}) {
  const [notebookId, setNotebookId] = useState('');
  const [newTitle, setNewTitle] = useState('');
  const [entryTitle, setEntryTitle] = useState('');
  const [content, setContent] = useState('');
  const [kind, setKind] = useState<'question' | 'conclusion'>('conclusion');
  const [entries, setEntries] = useState<{
    notebookId: string;
    values: NotebookEntry[];
  }>();
  const [revision, setRevision] = useState(0);
  const [message, setMessage] = useState('');
  const [saving, setSaving] = useState(false);
  useEffect(() => {
    if (!notebookId) return;
    const controller = new AbortController();
    void fetchNotebookEntries(notebookId, controller.signal)
      .then((values) => {
        if (!controller.signal.aborted) setEntries({ notebookId, values });
      })
      .catch((error) => {
        if (!controller.signal.aborted) setMessage(String(error));
      });
    return () => controller.abort();
  }, [notebookId, revision]);
  async function save(event: FormEvent, create: boolean) {
    event.preventDefault();
    setSaving(true);
    try {
      if (create) {
        const notebook = await createNotebook({
          title: newTitle.trim(),
          created_by: 'local-operator',
          incident_ids: incidentId ? [incidentId] : [],
        });
        setNotebookId(notebook.notebook_id);
        setNewTitle('');
      } else {
        await addNotebookEntry(notebookId, {
          kind,
          title: entryTitle.trim(),
          content: content.trim(),
          reference_id: null,
          created_by: 'local-operator',
        });
        setEntryTitle('');
        setContent('');
        setRevision((value) => value + 1);
      }
      setMessage('Notebook saved as non-evidence.');
      onSaved();
    } catch (error) {
      setMessage(
        error instanceof Error ? error.message : 'Notebook could not be saved.',
      );
    } finally {
      setSaving(false);
    }
  }
  return (
    <section className="notebook-editor" aria-label="Case notebooks">
      <h3>Case notebooks</h3>
      <p>
        Questions and conclusions remain analyst notes, separate from canonical
        evidence.
      </p>
      <form onSubmit={(event) => void save(event, true)}>
        <label>
          New notebook title
          <input
            aria-label="New notebook title"
            maxLength={500}
            value={newTitle}
            onChange={(event) => setNewTitle(event.target.value)}
          />
        </label>
        <button disabled={saving || !newTitle.trim()}>Create notebook</button>
      </form>
      <label>
        Notebook
        <select
          aria-label="Notebook"
          value={notebookId}
          onChange={(event) => setNotebookId(event.target.value)}
        >
          <option value="">Select a notebook</option>
          {notebooks.map((item) => (
            <option key={item.notebook_id} value={item.notebook_id}>
              {item.title}
            </option>
          ))}
        </select>
      </label>
      {notebookId && (
        <>
          <form onSubmit={(event) => void save(event, false)}>
            <label>
              Entry type
              <select
                value={kind}
                onChange={(event) =>
                  setKind(event.target.value as 'question' | 'conclusion')
                }
              >
                <option value="conclusion">Conclusion</option>
                <option value="question">Question</option>
              </select>
            </label>
            <label>
              Entry title
              <input
                aria-label="Entry title"
                value={entryTitle}
                maxLength={500}
                onChange={(event) => setEntryTitle(event.target.value)}
              />
            </label>
            <label>
              Entry content
              <textarea
                aria-label="Entry content"
                rows={5}
                maxLength={20000}
                value={content}
                onChange={(event) => setContent(event.target.value)}
              />
            </label>
            <button disabled={saving || !entryTitle.trim() || !content.trim()}>
              Add notebook entry
            </button>
          </form>
          {entries?.notebookId === notebookId ? (
            entries.values.map((item) => (
              <article key={item.entry_id}>
                <h4>{item.title}</h4>
                <p style={{ whiteSpace: 'pre-wrap' }}>{item.content}</p>
                <small>
                  {item.kind} · {item.created_by} · {item.created_at}
                </small>
              </article>
            ))
          ) : (
            <p role="status">Loading notebook…</p>
          )}
        </>
      )}
      {message && <p role="status">{message}</p>}
    </section>
  );
}
