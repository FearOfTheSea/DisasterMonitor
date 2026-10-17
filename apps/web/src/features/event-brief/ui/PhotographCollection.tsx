'use client';
/* eslint-disable @next/next/no-img-element -- Source previews retain original attribution. */

import { useState } from 'react';
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

export function PhotographCollection({ gallery }: { gallery: DisasterMediaGallery }) {
  const [page, setPage] = useState(0);
  const pageCount = Math.max(1, Math.ceil(gallery.items.length / 5));
  const current = Math.min(page, pageCount - 1);
  return (
    <section aria-label="Article photograph collection">
      <h4>Article photographs · {gallery.items.length} retained</h4>
      <p>
        {gallery.candidate_count ?? 'Unknown'} candidates · Retained asset limit:{' '}
        {gallery.collection_limit ?? 'Not recorded'}.{' '}
        {gallery.truncated
          ? 'Collection truncated; source articles remain accessible.'
          : 'Only eligible collected photographs are shown.'}
      </p>
      {gallery.items.slice(current * 5, (current + 1) * 5).map((item) => (
        <Photograph key={item.media_id} item={item} />
      ))}
      {pageCount > 1 ? (
        <nav aria-label="Photograph pages">
          <button
            type="button"
            disabled={current === 0}
            onClick={() => setPage(current - 1)}
          >
            Previous photographs
          </button>{' '}
          <span role="status">
            Page {current + 1} of {pageCount}
          </span>{' '}
          <button
            type="button"
            disabled={current === pageCount - 1}
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
