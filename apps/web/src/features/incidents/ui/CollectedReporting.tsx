'use client';

import { useEffect, useRef, useState } from 'react';
import { fetchCollectedReporting } from '@/features/incidents/api/collectedReportingClient';
import type { CollectedReportingResponse } from '@/shared/api/generated/assistant';
import { RetainedSourceText } from './RetainedSourceText';
import './collectedReporting.css';

const ELIGIBILITY = {
  eligible: 'Within reporting window',
  unknown_publication: 'Publication unknown',
  outside_interval: 'Publication outside this scan',
  unclassified: 'Classification unresolved',
  uncertain_publication: 'Publication may overlap the window boundary',
};

export function CollectedReporting({ scanId }: { scanId: string }) {
  const [open, setOpen] = useState(false);
  const [unlinkedOnly, setUnlinkedOnly] = useState(true);
  const [pages, setPages] = useState<CollectedReportingResponse[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const pending = useRef<AbortController | null>(null);
  const dialog = useRef<HTMLDialogElement | null>(null);
  useEffect(() => {
    const current = dialog.current;
    if (!current) return;
    if (open && !current.open) current.showModal();
    if (!open && current.open) current.close();
  }, [open]);
  useEffect(() => () => pending.current?.abort(), []);
  const last = pages.at(-1);
  const items = pages.flatMap((page) => page.items);

  async function load(reset = false, onlyUnlinked = unlinkedOnly) {
    if (pending.current && !reset) return;
    pending.current?.abort();
    const controller = new AbortController();
    pending.current = controller;
    setLoading(true);
    setError(null);
    if (reset) setPages([]);
    try {
      const page = await fetchCollectedReporting(
        scanId,
        reset ? 0 : (last?.next_offset ?? 0),
        reset ? null : (last?.version ?? null),
        onlyUnlinked,
        controller.signal,
      );
      if (!controller.signal.aborted)
        setPages((previous) => (reset ? [page] : [...previous, page]));
    } catch (reason) {
      if (!controller.signal.aborted)
        setError(
          reason instanceof Error
            ? reason.message
            : 'Collected reporting is unavailable.',
        );
    } finally {
      if (!controller.signal.aborted) setLoading(false);
      if (pending.current === controller) pending.current = null;
    }
  }

  return (
    <section className="collected-reporting" aria-label="Collected reporting">
      <button
        type="button"
        aria-expanded={open}
        onClick={() => {
          setOpen(!open);
          if (!open && !pages.length && !loading) void load(true);
        }}
      >
        {open ? 'Hide collected reporting' : 'Inspect collected reporting'}
      </button>
      <dialog
        ref={dialog}
        className="collected-reporting-dialog"
        aria-label="Collected reporting"
        onCancel={() => setOpen(false)}
        onClose={() => setOpen(false)}
      >
        {open ? (
          <>
            <header className="collected-reporting-header">
              <h3>Collected reporting</h3>
              <button type="button" onClick={() => setOpen(false)}>
                Close collected reporting
              </button>
            </header>
            <p>
              Collected sources may be unclassified or outside the reporting window.
              Review their publication and context before treating them as event
              evidence.
            </p>
            <label>
              <input
                type="checkbox"
                checked={unlinkedOnly}
                onChange={(event) => {
                  const checked = event.target.checked;
                  setUnlinkedOnly(checked);
                  void load(true, checked);
                }}
              />
              Only reports not shown with events
            </label>
            <button type="button" onClick={() => void load(true)}>
              Reload collected reports
            </button>
            {last ? (
              <p>
                {items.length} of {last.total} reports loaded.
              </p>
            ) : null}
            {loading ? <p role="status">Loading collected reporting…</p> : null}
            {error ? <p role="alert">{error}</p> : null}
            {last && !items.length ? (
              <p>No retained reports in this selection.</p>
            ) : null}
            <div className="collected-reporting-list">
              {items.map((item) => (
                <article key={item.capture_id} aria-label={item.source.title}>
                  <h4>
                    {/^https?:\/\//i.test(item.source.canonical_url) ? (
                      <a
                        href={item.source.canonical_url}
                        target="_blank"
                        rel="noreferrer"
                      >
                        {item.source.title}
                      </a>
                    ) : (
                      item.source.title
                    )}
                  </h4>
                  <p>
                    {item.source.publisher} · Byline:{' '}
                    {item.bylines.length ? item.bylines.join('; ') : 'Unknown'}
                  </p>
                  <p>
                    {item.origin
                      ? `Shared reporting origin: ${item.origin}`
                      : 'Reporting independence unknown.'}
                  </p>
                  <p>
                    {ELIGIBILITY[item.eligibility]} ·{' '}
                    {item.disaster?.replaceAll('_', ' ') ?? 'Unclassified'}
                  </p>
                  <p>
                    Published:{' '}
                    {item.source.published_at
                      ? new Date(item.source.published_at).toLocaleString()
                      : 'Unknown'}
                    {item.source.publication_precision === 'day' ? ' (date only)' : ''}
                    <br />
                    Updated:{' '}
                    {item.source.updated_at
                      ? new Date(item.source.updated_at).toLocaleString()
                      : 'Unknown'}
                    <br />
                    Retrieved: {new Date(item.source.retrieved_at).toLocaleString()}
                  </p>
                  <p>{item.text_preview}</p>
                  {item.access_issue ? <p>{item.access_issue}</p> : null}
                  <RetainedSourceText scanId={scanId} captureId={item.capture_id} />
                </article>
              ))}
            </div>
            {last?.next_offset != null && !error ? (
              <button type="button" disabled={loading} onClick={() => void load()}>
                Show more collected reports
              </button>
            ) : null}
          </>
        ) : null}
      </dialog>
    </section>
  );
}
