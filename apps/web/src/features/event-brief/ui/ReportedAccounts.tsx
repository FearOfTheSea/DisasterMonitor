'use client';

import { useState } from 'react';
import type { ReportedImpact } from '@/shared/api/generated/assistant';

export function ReportedAccounts({ accounts }: { accounts: ReportedImpact[] }) {
  const [page, setPage] = useState(0);
  const current = Math.min(page, Math.max(0, Math.ceil(accounts.length / 5) - 1));
  return (
    <section aria-label="Attributed impact accounts">
      <p>
        Source accounts may conflict. Inspect dates and geographic scopes; counts are
        not summed. Missing information is unknown, not zero.
      </p>
      {accounts
        .slice(current * 5, (current + 1) * 5)
        .map(({ fact, excerpt, qualifiers }, i) => (
          <article key={i}>
            <strong>
              {fact.label}: {fact.value}
            </strong>{' '}
            · {qualifiers?.join(', ')}
            {excerpt ? (
              <blockquote>{excerpt}</blockquote>
            ) : (
              <p>Supporting excerpt unavailable; inspect the source.</p>
            )}
            <a href={fact.source.canonical_url} target="_blank" rel="noreferrer">
              {fact.source.publisher}: {fact.source.title}
            </a>
            <p>
              Published: {fact.source.published_at ?? 'Unknown'} · Updated:{' '}
              {fact.source.updated_at ?? 'Unknown'} · Retrieved:{' '}
              {fact.source.retrieved_at}
            </p>
            <p>
              Observed: {fact.observed_at ?? 'Unknown'} · Scope:{' '}
              {fact.reported_location ?? 'Unknown'}
            </p>
          </article>
        ))}
      {accounts.length > 5 ? (
        <nav aria-label="Impact account pages">
          <button
            type="button"
            disabled={current === 0}
            onClick={() => setPage(current - 1)}
          >
            Previous accounts
          </button>{' '}
          <span role="status">
            Page {current + 1} of {Math.ceil(accounts.length / 5)}
          </span>{' '}
          <button
            type="button"
            disabled={(current + 1) * 5 >= accounts.length}
            onClick={() => setPage(current + 1)}
          >
            Next accounts
          </button>
        </nav>
      ) : null}
    </section>
  );
}
