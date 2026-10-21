'use client';

import { useState } from 'react';
import type { IncidentGeometry } from '@/features/incidents/model/activeIncidents';
import { disasterLabel } from './incidentPresentation';
import type {
  DiscoveryReportResponse,
  ReportedImpactResponse,
} from '@/shared/api/generated/assistant';

const PAGE_SIZE = 5;
const IMPACTS = [
  ['fatalities', 'Fatalities'],
  ['injuries', 'Injuries'],
  ['displacement', 'Displacement'],
  ['roads_bridges', 'Roads and bridges'],
  ['electricity', 'Electricity networks'],
  ['water', 'Water systems'],
  ['communications', 'Communications networks'],
] as const;

function time(value?: string | null) {
  return value ? new Date(value).toLocaleString() : 'Unknown';
}

function Pages<T>({
  items,
  label,
  render,
}: {
  items: T[];
  label: string;
  render: (item: T, index: number) => React.ReactNode;
}) {
  const [page, setPage] = useState(0);
  const current = Math.min(page, Math.max(0, Math.ceil(items.length / PAGE_SIZE) - 1));
  return (
    <>
      {items.slice(current * PAGE_SIZE, (current + 1) * PAGE_SIZE).map(render)}
      {items.length > PAGE_SIZE ? (
        <nav aria-label={`${label} pages`}>
          <button
            type="button"
            disabled={current === 0}
            onClick={() => setPage(current - 1)}
          >
            Previous {label}
          </button>{' '}
          <span role="status">
            {current * PAGE_SIZE + 1}–
            {Math.min((current + 1) * PAGE_SIZE, items.length)} of {items.length}
          </span>{' '}
          <button
            type="button"
            disabled={(current + 1) * PAGE_SIZE >= items.length}
            onClick={() => setPage(current + 1)}
          >
            Next {label}
          </button>
        </nav>
      ) : null}
    </>
  );
}

function ReportTimes({ report }: { report: DiscoveryReportResponse }) {
  const published =
    report.source.publication_precision === 'day' && report.source.published_at
      ? `${report.source.published_at.slice(0, 10)} (date only; exact time unknown)`
      : time(report.source.published_at);
  const eventDate = report.event_date_wording
    ? `${report.event_date_wording} (${report.event_date_precision}${report.event_year_inferred ? '; year inferred from publication context' : ''})`
    : time(report.event_time);
  return (
    <p className="event-report-times">
      Published: {published} · Updated: {time(report.source.updated_at)} · Indexed:{' '}
      {time(report.indexed_at)} · Retrieved: {time(report.source.retrieved_at)}
      <br />
      Reported event time: {eventDate} · Reported place: {report.location ?? 'Unknown'}
      {report.mention_id
        ? ` · ${report.location_precision} · ${report.mention_role} mention`
        : ''}
    </p>
  );
}

function Lineage({ report }: { report: DiscoveryReportResponse }) {
  return (
    <p>
      {report.origin
        ? `Shared reporting origin: ${report.origin}`
        : 'Reporting independence unknown.'}
    </p>
  );
}

function Article({ report }: { report: DiscoveryReportResponse }) {
  return (
    <article className="event-collected-article">
      <h4>
        <a href={report.source.canonical_url} target="_blank" rel="noreferrer">
          {report.source.publisher}: {report.source.title}
        </a>
      </h4>
      <ReportTimes report={report} />
      {report.original_url ? (
        <p>
          <a href={report.original_url} target="_blank" rel="noreferrer">
            Original publisher article
          </a>
        </p>
      ) : null}
      <Lineage report={report} />
      {report.mention_excerpt ? (
        <blockquote>{report.mention_excerpt}</blockquote>
      ) : null}
      {report.mention_notices?.map((notice) => (
        <p key={notice}>{notice}</p>
      ))}
      {report.access_issue ? <p>{report.access_issue}</p> : null}
      {!report.claims?.length
        ? report.fatality_evidence?.map((excerpt) => (
            <blockquote key={excerpt}>
              {excerpt}
              <br />
              Reported by {report.source.publisher}; unverified claim.
            </blockquote>
          ))
        : null}
    </article>
  );
}

export function ArticleCollection({
  reports,
  notices = [],
  mappedGeometry,
}: {
  reports: DiscoveryReportResponse[];
  notices?: string[];
  mappedGeometry?: IncidentGeometry | null;
}) {
  const mapped =
    mappedGeometry?.kind !== 'descriptive' &&
    Boolean(mappedGeometry?.coordinates.length);
  const articles = [
    ...new Map(reports.map((report) => [report.source.canonical_url, report])).values(),
  ];
  const dated = articles
    .filter((r) => r.source.published_at)
    .toSorted(
      (a, b) =>
        Date.parse(b.source.published_at!) - Date.parse(a.source.published_at!) ||
        a.source.canonical_url.localeCompare(b.source.canonical_url),
    );
  const undated = articles.filter((r) => !r.source.published_at);
  const claims = reports.flatMap((report) =>
    (report.claims ?? []).map((claim) => ({ report, claim })),
  );
  const episodes = [
    ...new Map(
      reports.flatMap((report) =>
        report.episode_account
          ? [
              [
                report.episode_account.account_id,
                { report, account: report.episode_account },
              ] as const,
            ]
          : [],
      ),
    ).values(),
  ];
  const comparableAccounts = new Map<string, Set<string>>();
  for (const { claim } of claims) {
    if (!IMPACTS.some(([category]) => category === claim.category)) continue;
    const value = claim.value.toLowerCase();
    if (value.includes('unknown')) continue;
    // A subtype count and a broader injury account can overlap. Compare only
    // accounts with the same category and label; keep every source separately.
    const key = `${claim.category}:${claim.label.toLowerCase()}`;
    const values = comparableAccounts.get(key) ?? new Set<string>();
    values.add(value);
    comparableAccounts.set(key, values);
  }
  const differing = [...comparableAccounts.values()].some((values) => values.size > 1);
  return (
    <>
      <section aria-label="Reported impacts">
        <h3>Reported impacts</h3>
        <p>
          Source accounts remain unverified. Counts are not added or selected as truth.
          Different dates, geographic scopes, overlapping populations, or corrections
          may explain differences. Shared origins are not independent confirmation.
        </p>
        {differing ? (
          <p role="status" className="event-uncertainty">
            Differing accounts: inspect each source’s scope and dates. Newer reporting
            is not automatically correct.
          </p>
        ) : null}
        {IMPACTS.map(([category, label]) => {
          const accounts = claims.filter((c) => c.claim.category === category);
          return (
            <details key={label} className="event-impact-accounts">
              <summary>
                {label}
                {accounts.length ? ` · ${accounts.length} accounts` : ': Unknown'}
              </summary>
              {accounts.length ? (
                <Pages
                  items={accounts}
                  label={`${label.toLowerCase()} claims`}
                  render={(
                    {
                      report,
                      claim,
                    }: {
                      report: DiscoveryReportResponse;
                      claim: ReportedImpactResponse;
                    },
                    index,
                  ) => (
                    <article key={`${report.source.canonical_url}:${index}`}>
                      <strong>
                        {claim.label}: {claim.value}
                      </strong>{' '}
                      · {claim.qualifiers?.join(', ') || 'Qualification not extracted'}
                      <blockquote>{claim.excerpt}</blockquote>
                      <a
                        href={report.source.canonical_url}
                        target="_blank"
                        rel="noreferrer"
                      >
                        {report.source.publisher}: {report.source.title}
                      </a>
                      <ReportTimes report={report} />
                      <Lineage report={report} />
                    </article>
                  )}
                />
              ) : (
                <p>No in-scope account extracted. Unknown does not mean zero.</p>
              )}
            </details>
          );
        })}
      </section>
      {episodes.length ? (
        <section aria-label="Combined episode accounts">
          <h3>Combined episode accounts</h3>
          <p>
            These source accounts cover a combined episode. They are not allocated to
            individual hazards or localities. Counts may overlap other accounts; do not
            add them.
          </p>
          <Pages
            items={episodes}
            label="combined accounts"
            render={({ report, account }) => (
              <article key={account.account_id}>
                <h4>{account.hazards.map(disasterLabel).join(' + ')}</h4>
                <p>
                  Reported episode context: {account.location} · Source event date:{' '}
                  {account.event_date_wording}
                </p>
                {account.claims.map((claim, index) => (
                  <div key={index}>
                    <strong>
                      {claim.label}: {claim.value}
                    </strong>
                    <p>
                      {claim.qualifiers?.join(', ') || 'Qualification not extracted'}
                    </p>
                    <blockquote>{claim.excerpt}</blockquote>
                  </div>
                ))}
                <a href={report.source.canonical_url} target="_blank" rel="noreferrer">
                  {report.source.publisher}: {report.source.title}
                </a>
                <ReportTimes report={report} />
                <Lineage report={report} />
                <details>
                  <summary>Combined account source passages</summary>
                  <blockquote>{account.excerpt}</blockquote>
                </details>
              </article>
            )}
          />
        </section>
      ) : null}
      <section aria-label="Discovery reporting">
        <h3>Collected articles · {articles.length}</h3>
        <p>
          The five latest dated collected articles appear first. Every retained report
          is accessible below.
        </p>
        <section aria-label="Dated articles">
          <Pages
            items={dated}
            label="articles"
            render={(report) => (
              <Article key={report.source.canonical_url} report={report} />
            )}
          />
          {!dated.length ? <p>No dated articles collected.</p> : null}
        </section>
        <details>
          <summary>Unknown publication times · {undated.length}</summary>
          <p>
            Indexing and retrieval times do not establish publication time. These
            accounts do not establish reporting-window eligibility.
          </p>
          <Pages
            items={undated}
            label="undated articles"
            render={(report) => (
              <Article key={report.source.canonical_url} report={report} />
            )}
          />
        </details>
        <details>
          <summary>Collection and access limits</summary>
          {notices.map((notice, i) => (
            <p key={i}>{notice}</p>
          ))}
        </details>
      </section>
      <section aria-label="Reported locations">
        <h3>Reported locations</h3>
        <p>
          Source geometry retains its reported precision. Administrative areas are
          context, not measured damage boundaries. Imagery inspection buffers are not
          affected-area evidence.
        </p>
        <Pages
          items={reports.filter((r) => r.location || r.geometry)}
          label="locations"
          render={(report) => (
            <article key={report.mention_id ?? report.source.canonical_url}>
              <p>
                {report.location ?? report.geometry?.description ?? 'Source geometry'} ·{' '}
                {report.geometry?.kind ?? 'Descriptive place; coordinates unavailable'}
                {report.geometry?.estimated ? ' · estimated' : ''}
              </p>
              {report.geometry?.coordinates?.length ? (
                <details>
                  <summary>Source coordinates (latitude, longitude)</summary>
                  <p>
                    {report.geometry.coordinates
                      .map((point) => `${point.latitude}, ${point.longitude}`)
                      .join(' · ')}
                  </p>
                  <p>{report.geometry.description}</p>
                </details>
              ) : null}
              <a href={report.source.canonical_url} target="_blank" rel="noreferrer">
                Location source: {report.source.publisher}
              </a>
            </article>
          )}
        />
        {mapped ? (
          <p>
            Selected event map geometry:{' '}
            {(mappedGeometry?.description ?? mappedGeometry?.kind)?.replace(
              /[.\s]+$/,
              '',
            )}
            .
            {mappedGeometry?.estimated
              ? ' This estimated context is not an exact event location or measured affected area.'
              : ' This retains the supplied source precision; it does not by itself establish a measured affected area.'}{' '}
            Article place descriptions above retain their own source precision.
          </p>
        ) : !reports.some(
            (r) =>
              r.geometry?.kind !== 'descriptive' && r.geometry?.coordinates?.length,
          ) ? (
          <p>
            Location unresolved for mapping. This event remains inspectable in the list.
          </p>
        ) : null}
      </section>
    </>
  );
}
