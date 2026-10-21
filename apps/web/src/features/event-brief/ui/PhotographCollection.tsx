'use client';
/* eslint-disable @next/next/no-img-element -- Source previews retain original attribution. */

import { useEffect, useRef, useState } from 'react';
import type {
  DisasterMediaGallery,
  DisasterMediaItem,
} from '@/shared/api/generated/assistant';
import { API_BASE_URL } from '@/shared/config/runtime';

function Photograph({ item }: { item: DisasterMediaItem }) {
  const [broken, setBroken] = useState(false);
  return (
    <figure className="event-photograph">
      {broken ? (
        <p role="status">Photograph unavailable. Open the source article below.</p>
      ) : (
        <img
          src={`${API_BASE_URL}/media/${encodeURIComponent(item.media_id)}`}
          alt={item.caption}
          loading="lazy"
          width={item.width}
          height={item.height}
          onError={() => setBroken(true)}
        />
      )}
      <figcaption>
        <p>{item.caption}</p>
        <p>
          {item.credit} ({item.credit_kind}) · {item.publisher} · Captured:{' '}
          {item.captured_at ?? 'Unknown'} · Published: {item.published_at ?? 'Unknown'}
        </p>
        <p>
          {item.rights_status.replaceAll('_', ' ')} ·{' '}
          {item.license_name ?? 'Reuse license not established'}
        </p>
        <a href={item.source_page_url} target="_blank" rel="noreferrer">
          {item.publisher}: source article and rights
        </a>
        {item.source_references?.map((source, i) => (
          <p key={i}>
            <a href={source.source_page_url} target="_blank" rel="noreferrer">
              {source.publisher}: source reference
            </a>{' '}
            · {source.caption} · {source.credit} ({source.credit_kind}) · Captured:{' '}
            {source.captured_at ?? 'Unknown'} · Published:{' '}
            {source.published_at ?? 'Unknown'} ·{' '}
            {source.rights_status.replaceAll('_', ' ')}
          </p>
        ))}
        <p>
          {item.association_detail} {item.uncertainty}
        </p>
      </figcaption>
    </figure>
  );
}

export function PhotographCollection({
  gallery,
  onLoadBatch,
}: {
  gallery: DisasterMediaGallery;
  onLoadBatch?: (cursor: string | undefined, signal: AbortSignal) => Promise<void>;
}) {
  const [page, setPage] = useState(0);
  const [cursor, setCursor] = useState<string>();
  const [history, setHistory] = useState<Array<string | undefined>>([]);
  const [earlier, setEarlier] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string>();
  const request = useRef<AbortController | undefined>(undefined);
  useEffect(() => () => request.current?.abort(), []);
  async function loadBatch(
    next: string | undefined,
    previous: Array<string | undefined>,
    trimmed = earlier,
  ) {
    if (!onLoadBatch || request.current) return;
    const controller = new AbortController();
    request.current = controller;
    setLoading(true);
    setError(undefined);
    try {
      await onLoadBatch(next, controller.signal);
      if (!controller.signal.aborted) {
        setCursor(next);
        setHistory(previous.slice(-32));
        setEarlier(trimmed || previous.length > 32);
        setPage(0);
      }
    } catch (failure) {
      if (!controller.signal.aborted)
        setError(
          failure instanceof Error ? failure.message : 'Photograph collection failed.',
        );
    } finally {
      request.current = undefined;
      if (!controller.signal.aborted) setLoading(false);
    }
  }
  const pageCount = Math.max(1, Math.ceil(gallery.items.length / 5));
  const current = Math.min(page, pageCount - 1);
  return (
    <section aria-label="Article photograph collection">
      <h4>Article photographs · {gallery.items.length} retained</h4>
      <p>
        {gallery.candidate_count ?? 'Unknown'} candidates in this batch · Batch asset
        limit: {gallery.collection_limit ?? 'Not recorded'}.{' '}
        {gallery.next_cursor
          ? 'More source photographs remain available through Continue photograph collection.'
          : gallery.truncated
            ? 'Collection truncated; source articles remain accessible.'
            : 'Only eligible collected photographs are shown.'}
      </p>
      {onLoadBatch ? (
        <nav aria-label="Photograph collection batches">
          {history.length ? (
            <button
              type="button"
              disabled={loading}
              onClick={() => void loadBatch(history.at(-1), history.slice(0, -1))}
            >
              Previous collected batch
            </button>
          ) : null}{' '}
          {gallery.next_cursor ? (
            <button
              type="button"
              disabled={loading}
              onClick={() =>
                void loadBatch(gallery.next_cursor ?? undefined, [...history, cursor])
              }
            >
              Continue photograph collection
            </button>
          ) : null}{' '}
          <button
            type="button"
            disabled={loading}
            onClick={() => void loadBatch(undefined, [], false)}
          >
            Restart photographs
          </button>
          {earlier ? (
            <p>Earlier batches remain accessible from Restart photographs.</p>
          ) : null}
          {loading ? (
            <p role="status">
              Collecting the next photographs. Current photographs remain available.
            </p>
          ) : null}
          {error ? (
            <p role="status">{error} Current photographs remain available.</p>
          ) : null}
        </nav>
      ) : null}
      {gallery.items.slice(current * 5, (current + 1) * 5).map((item) => (
        <Photograph key={item.media_id} item={item} />
      ))}
      {pageCount > 1 ? (
        <nav aria-label="Photograph pages">
          <button
            type="button"
            disabled={loading || current === 0}
            onClick={() => setPage(current - 1)}
          >
            Previous photographs
          </button>{' '}
          <span role="status">
            Page {current + 1} of {pageCount}
          </span>{' '}
          <button
            type="button"
            disabled={loading || current === pageCount - 1}
            onClick={() => setPage(current + 1)}
          >
            Next photographs
          </button>
        </nav>
      ) : null}
      {gallery.unavailable_sources?.map((source, i) => (
        <article key={i}>
          <p>{source.detail}</p>
          <a href={source.source_page_url} target="_blank" rel="noreferrer">
            {source.publisher}: open source article
          </a>
        </article>
      ))}
      <details>
        <summary>
          All collected source articles · {gallery.source_articles?.length ?? 0}
        </summary>
        {gallery.source_articles?.map((source) => (
          <p key={source.canonical_url}>
            <a href={source.canonical_url} target="_blank" rel="noreferrer">
              {source.publisher}: {source.title}
            </a>
          </p>
        ))}
      </details>
      <p>{gallery.rejected_count} candidates rejected or deduplicated.</p>
      {gallery.rejection_reasons?.map(([reason, count]) => (
        <p key={reason}>
          {reason.replaceAll('_', ' ')}: {count}
        </p>
      ))}
    </section>
  );
}
