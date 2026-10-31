'use client';

import { useEffect, useRef, useState } from 'react';
import { fetchIndexedReporting } from '@/features/incidents/api/indexedReportingClient';
import type { IndexedReportingResponse } from '@/shared/api/generated/assistant';
import './collectedReporting.css';

const INDEX_NAMES: Record<string, string> = {
  'bing-rss-discovery': 'Bing News',
  'google-rss-discovery': 'Google News',
  'gdelt-discovery': 'GDELT',
  'gdelt-gkg-discovery': 'GDELT GKG',
  'gdelt-archive-discovery': 'GDELT archive',
  'wikipedia-citation-discovery': 'Wikipedia citations',
  'reliefweb-discovery': 'ReliefWeb',
};
const time = (value: string | null) =>
  value === null ? 'Unknown' : new Date(value).toLocaleString();

export function IndexedReporting({
  scanId,
  intervalStart,
  intervalEnd,
}: {
  scanId: string;
  intervalStart: string;
  intervalEnd: string;
}) {
  const [open, setOpen] = useState(false);
  const [search, setSearch] = useState('');
  const [pages, setPages] = useState<IndexedReportingResponse[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const pending = useRef<AbortController | null>(null);
  const dialog = useRef<HTMLDialogElement | null>(null);
  const last = pages.at(-1);
  const items = pages.flatMap((page) => page.items);

  useEffect(() => {
    const current = dialog.current;
    if (!current) return;
    if (open && !current.open) current.showModal();
    if (!open && current.open) current.close();
  }, [open]);
  useEffect(() => () => pending.current?.abort(), []);

  function close() {
    pending.current?.abort();
    pending.current = null;
    setLoading(false);
    setOpen(false);
  }

  async function load(reset: boolean) {
    if (pending.current && !reset) return;
    pending.current?.abort();
    const controller = new AbortController();
    pending.current = controller;
    setLoading(true);
    setError(null);
    if (reset) setPages([]);
    try {
      const page = await fetchIndexedReporting(
        scanId,
        reset ? search : (last?.query ?? ''),
        reset ? null : (last?.next_cursor ?? null),
        reset ? null : (last?.snapshot ?? null),
        controller.signal,
      );
      if (!controller.signal.aborted)
        setPages((previous) => (reset ? [page] : [...previous, page]));
    } catch (reason) {
      if (!controller.signal.aborted)
        setError(
          reason instanceof Error
            ? reason.message
            : 'Indexed reporting is unavailable.',
        );
    } finally {
      if (!controller.signal.aborted) setLoading(false);
      if (pending.current === controller) pending.current = null;
    }
  }

  return (
    <section className="collected-reporting" aria-label="Indexed reporting">
      <button
        type="button"
        aria-expanded={open}
        onClick={() => {
          setOpen(true);
          if (!pages.length && !loading) void load(true);
        }}
      >
        Inspect indexed reporting
      </button>
      <dialog
        ref={dialog}
        className="collected-reporting-dialog"
        aria-label="Indexed reporting"
        onCancel={close}
        onClose={close}
      >
        {open ? (
          <>
            <header className="collected-reporting-header">
              <h3>Indexed reporting</h3>
              <button type="button" onClick={close}>
                Close indexed reporting
              </button>
            </header>
            <p>
              Headlines, links and excerpts returned by news indexes remain available
              even when article access is pending or unavailable. Index wording can be
              incomplete or wrong; it is not retained publisher text or verified impact
              evidence.
            </p>
            <p>
              Publication time is separate from indexing time. Repeated links preserve
              separate index observations and do not represent additional events.
            </p>
            <form
              onSubmit={(event) => {
                event.preventDefault();
                void load(true);
              }}
            >
              <label htmlFor="indexed-reporting-search">Search indexed reporting</label>
              <input
                id="indexed-reporting-search"
                type="search"
                maxLength={200}
                value={search}
                onChange={(event) => setSearch(event.target.value)}
              />
              <button type="submit" disabled={loading}>
                Search index entries
              </button>
            </form>
            {last ? (
              <p>
                {items.length} index observations loaded
                {last.query ? ` for “${last.query}”` : ''}.
              </p>
            ) : null}
            {loading ? <p role="status">Loading indexed reporting…</p> : null}
            {error ? <p role="alert">{error}</p> : null}
            {last && !items.length ? (
              <p>No matching index observations in this scan.</p>
            ) : null}
            <div className="collected-reporting-list">
              {items.map((item) => (
                <article key={item.observation_id} aria-label={item.title}>
                  <h4>
                    <a href={item.canonical_url} target="_blank" rel="noreferrer">
                      {item.publisher}: {item.title}
                    </a>
                  </h4>
                  <p>
                    Published: {time(item.published_at)} · Updated:{' '}
                    {time(item.updated_at)}
                  </p>
                  <p>
                    {item.published_at === null
                      ? 'Publication time unknown; reporting-window eligibility is unresolved.'
                      : Date.parse(item.published_at) < Date.parse(intervalStart) ||
                          Date.parse(item.published_at) > Date.parse(intervalEnd)
                        ? 'Publication outside this scan’s reporting window.'
                        : 'The index reports publication within this window; publisher timing has not been verified.'}
                  </p>
                  {item.index_excerpt ? (
                    <p>Index excerpt: {item.index_excerpt}</p>
                  ) : null}
                  <details>
                    <summary>Index provenance and wording</summary>
                    <p>
                      Index: {INDEX_NAMES[item.provider] ?? item.provider} · Indexed:{' '}
                      {time(item.indexed_at)} · Observed: {time(item.observed_at)}
                    </p>
                    {item.search_wording && item.search_wording !== item.title ? (
                      <p>
                        Additional index wording (unverified): {item.search_wording}
                      </p>
                    ) : null}
                    <p>Observation: {item.observation_id}</p>
                  </details>
                </article>
              ))}
            </div>
            {last?.next_cursor ? (
              <button type="button" disabled={loading} onClick={() => void load(false)}>
                Load more index entries
              </button>
            ) : null}
          </>
        ) : null}
      </dialog>
    </section>
  );
}
