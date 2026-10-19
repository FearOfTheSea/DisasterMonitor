'use client';

import type { ReportingDays } from '@/features/incidents/api/discoveryClient';
import type { DiscoveryScanResponse } from '@/shared/api/generated/assistant';
import { isContextOnlyIncident } from '@/features/incidents/model/activeIncidents';

export function DiscoveryScanControls({
  days,
  onDaysChange,
  onScan,
  run,
  error,
  submitting = false,
  onClear,
  onReprocess,
  onContinue,
}: {
  days: ReportingDays;
  onDaysChange: (days: ReportingDays) => void;
  onScan: () => void | Promise<void>;
  run?: DiscoveryScanResponse;
  error?: string;
  submitting?: boolean;
  onClear?: () => void;
  onReprocess?: () => void | Promise<void>;
  onContinue?: () => void | Promise<void>;
}) {
  const running = submitting || run?.status === 'running';
  const contextCount =
    run?.snapshot.incidents?.filter(isContextOnlyIncident).length ?? 0;
  const title = submitting
    ? 'Updating reporting…'
    : !run
      ? undefined
      : run.collection?.state === 'waiting'
        ? 'Waiting for a news service — available results retained'
        : run.status === 'running'
          ? 'Scanning the world…'
          : run.status === 'failed'
            ? 'Scan failed'
            : run.status === 'incomplete'
              ? 'Scan incomplete — available results retained'
              : run.snapshot.incidents?.length
                ? 'Scan completed'
                : 'No matching events were found in this scan';
  return (
    <section className="discovery-scan-controls" aria-label="Worldwide discovery">
      <label>
        Reporting period
        <select
          aria-label="Reporting period"
          value={days}
          onChange={(event) =>
            onDaysChange(Number(event.target.value) as ReportingDays)
          }
          disabled={running}
        >
          <option value={1}>Past 24 hours</option>
          <option value={3}>Past 3 days</option>
          <option value={7}>Past 7 days</option>
          <option value={14}>Past 14 days</option>
          <option value={30}>Past 30 days</option>
        </select>
      </label>
      <button type="button" onClick={() => void onScan()} disabled={running}>
        {submitting ? 'Updating…' : running ? 'Scanning…' : 'Scan the world'}
      </button>
      <p>
        Scanning may take a while. The reporting interval is fixed at scan start and
        uses article publication time.
      </p>
      {title ? (
        <div role={run?.status === 'failed' ? 'alert' : 'status'} aria-live="polite">
          <strong>{title}</strong>
          {run ? (
            <>
              <p>
                {new Date(run.interval_start).toLocaleString()} –{' '}
                {new Date(run.interval_end).toLocaleString()}
              </p>
              <p>
                {run.associated_event_count ?? 0} associated physical events ·{' '}
                {Math.max(
                  0,
                  (run.candidate_count ?? run.snapshot.incidents?.length ?? 0) -
                    contextCount,
                )}{' '}
                unresolved event candidates · {contextCount} context/fragment records ·{' '}
                {run.reports_seen} collected reports.
              </p>
              {run.uncertain_publication_count ? (
                <p>
                  {run.uncertain_publication_count} reports overlap the window boundary
                  with date-only publication. Their candidates remain inspectable;
                  window eligibility is uncertain.
                </p>
              ) : null}
              <p>{run.coverage_notice}</p>
              {run.collection ? (
                <>
                  <p>
                    {run.collection.pages_acquired} pages collected ·{' '}
                    {run.collection.searches_pending} planned searches remain ·{' '}
                    {run.collection.articles_pending} articles awaiting retrieval.
                  </p>
                  {run.collection.articles_unavailable ? (
                    <p>
                      {run.collection.articles_unavailable} articles could not be
                      retrieved. Their leads and access outcomes remain retained.
                    </p>
                  ) : null}
                  {run.collection.retry_at ? (
                    <p>
                      News service retry:{' '}
                      {new Date(run.collection.retry_at).toLocaleString()}. Continuing
                      respects this wait.
                    </p>
                  ) : null}
                </>
              ) : null}
              {run.reprocessed_from ? (
                <p>
                  These results reprocess retained reports. No new news search was
                  performed.
                </p>
              ) : null}
              {run.unlocated_count > 0 ? (
                <p>
                  {run.unlocated_count}{' '}
                  {run.unlocated_count === 1
                    ? 'record has an unresolved location and remains'
                    : 'records have unresolved locations and remain'}{' '}
                  accessible in the list.
                </p>
              ) : null}
              {run.issues.length ? (
                <details>
                  <summary>Acquisition limits and notices</summary>
                  <ul>
                    {run.issues.map((issue) => (
                      <li key={issue}>{issue}</li>
                    ))}
                  </ul>
                </details>
              ) : null}
            </>
          ) : null}
        </div>
      ) : null}
      {error ? <p role="alert">{error}</p> : null}
      {run?.collection?.can_continue && !run.reprocessed_from && onContinue ? (
        <>
          <button type="button" disabled={running} onClick={() => void onContinue()}>
            Continue collection
          </button>
          <p>
            Resume remaining news searches and article retrieval for this same reporting
            interval.
          </p>
        </>
      ) : null}
      {run && onReprocess ? (
        <>
          <button type="button" disabled={running} onClick={() => void onReprocess()}>
            Reprocess retained reports
          </button>
          <p>
            Reassess collected reporting without another news search. The original scan
            remains available.
          </p>
        </>
      ) : null}
      {run && onClear ? (
        <button type="button" onClick={onClear}>
          Browse provider catalogs
        </button>
      ) : null}
    </section>
  );
}
