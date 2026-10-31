'use client';

import { useEffect, useRef, useState } from 'react';
import { fetchCollectedReportingText } from '@/features/incidents/api/collectedReportingClient';
import { fetchRetainedReporting } from '@/features/incidents/api/retainedReportingClient';
import type { RetainedReportingPageResponse } from '@/shared/api/generated/assistant';

export function RetainedSourceText({
  incidentId,
  scanId,
  captureId,
}: ({ incidentId: string; scanId?: never } | { scanId: string; incidentId?: never }) & {
  captureId: string;
}) {
  const [expanded, setExpanded] = useState(false);
  const [pages, setPages] = useState<RetainedReportingPageResponse[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const pending = useRef<AbortController | null>(null);
  useEffect(() => () => pending.current?.abort(), []);
  const last = pages.at(-1);

  async function load() {
    if (pending.current) return;
    const controller = new AbortController();
    pending.current = controller;
    setLoading(true);
    setError(null);
    try {
      const owner = scanId ?? incidentId;
      if (!owner) throw new Error('Retained source context is unavailable.');
      const fetchPage =
        scanId === undefined ? fetchRetainedReporting : fetchCollectedReportingText;
      const page = await fetchPage(
        owner,
        captureId,
        last?.next_offset ?? 0,
        controller.signal,
      );
      if (!controller.signal.aborted) setPages((previous) => [...previous, page]);
    } catch (reason) {
      if (!controller.signal.aborted)
        setError(
          reason instanceof Error
            ? reason.message
            : 'Retained source text is unavailable.',
        );
    } finally {
      if (!controller.signal.aborted) setLoading(false);
      if (pending.current === controller) pending.current = null;
    }
  }

  return (
    <section aria-label="Retained source text">
      <button
        type="button"
        aria-expanded={expanded}
        onClick={() => {
          setExpanded(!expanded);
          if (!expanded && !pages.length && !error) void load();
        }}
      >
        {expanded ? 'Hide retained source text' : 'Read retained source text'}
      </button>
      {expanded ? (
        <>
          <p>
            {scanId !== undefined
              ? 'Source text may describe multiple occurrences. Publication and event classification may be unresolved.'
              : 'Source text may describe other places or occurrences. It does not establish this event’s toll or physical identity.'}
          </p>
          {pages.length ? (
            <blockquote className="event-retained-source-text">
              {pages.map((page) => page.text).join('')}
            </blockquote>
          ) : null}
          {last?.unavailable_reason ? <p>{last.unavailable_reason}</p> : null}
          {loading ? <p role="status">Loading retained source text…</p> : null}
          {error ? (
            <>
              <p role="alert">{error}</p>
              <button type="button" disabled={loading} onClick={() => void load()}>
                Retry source text
              </button>
            </>
          ) : null}
          {last && !error && last.next_offset != null ? (
            <button type="button" disabled={loading} onClick={() => void load()}>
              Read more source text
            </button>
          ) : null}
        </>
      ) : null}
    </section>
  );
}
