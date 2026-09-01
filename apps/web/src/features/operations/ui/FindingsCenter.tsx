'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';

import type {
  ActiveIncident,
  ActiveIncidentsSnapshot,
  CompoundHazardCorrelation,
} from '@/features/incidents/model/activeIncidents';
import {
  fetchIncidentWatches,
  fetchIncidentWatchTimeline,
  markIncidentWatchTimelineRead,
} from '@/features/operations/api/incidentWatches';
import type {
  IncidentWatch,
  IncidentWatchChange,
} from '@/features/operations/model/incidentWatch';
import {
  buildOperationalFindings,
  type OperationalFindingKind,
} from '@/features/operations/model/operationalFinding';

type FindingsCenterProps = {
  activeSnapshot?: ActiveIncidentsSnapshot;
  displayedIncidents: readonly ActiveIncident[];
  displayedCorrelations: readonly CompoundHazardCorrelation[];
  onSelectIncident: (incident: ActiveIncident) => void;
  onWatchDataChange?: () => void;
  refreshToken?: number;
};

const KIND_LABELS: Record<OperationalFindingKind, string> = {
  watch_change: 'Unread watch change',
  watch_coverage: 'Watch coverage',
  active_coverage: 'Active Incidents coverage',
  active_warning: 'Retrieval warning',
  compound_correlation: 'Descriptive correlation',
};

function formatTime(value: string): string {
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleString();
}

async function fetchWatchFindingData(signal?: AbortSignal) {
  const watches = await fetchIncidentWatches(signal);
  const watchesWithUnread = watches.filter((watch) => watch.unread_change_count > 0);
  const timelineResults = await Promise.all(
    watchesWithUnread.map(async (watch) => {
      try {
        return {
          changes: await fetchIncidentWatchTimeline(watch.watch_id, signal),
        };
      } catch (caught) {
        if (caught instanceof DOMException && caught.name === 'AbortError') {
          throw caught;
        }
        return {
          changes: [] as IncidentWatchChange[],
          error:
            caught instanceof Error
              ? caught.message
              : `Timeline for ${watch.watch_id} failed.`,
        };
      }
    }),
  );
  return {
    watches,
    changes: timelineResults.flatMap((result) => result.changes),
    timelineError: timelineResults.find((result) => result.error)?.error,
  };
}

export function FindingsCenter({
  activeSnapshot,
  displayedIncidents,
  displayedCorrelations,
  onSelectIncident,
  onWatchDataChange,
  refreshToken = 0,
}: FindingsCenterProps) {
  const [watches, setWatches] = useState<IncidentWatch[]>([]);
  const [watchChanges, setWatchChanges] = useState<IncidentWatchChange[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string>();
  const [markingChangeId, setMarkingChangeId] = useState<string>();

  const load = useCallback(async (signal?: AbortSignal) => {
    setLoading(true);
    setError(undefined);
    try {
      const result = await fetchWatchFindingData(signal);
      if (signal?.aborted) return;
      setWatches(result.watches);
      setWatchChanges(result.changes);
      if (result.timelineError) {
        setError(`Some watch findings are unavailable: ${result.timelineError}`);
      }
    } catch (caught) {
      if (!(caught instanceof DOMException && caught.name === 'AbortError')) {
        setError(caught instanceof Error ? caught.message : 'Findings failed to load.');
      }
    } finally {
      if (!signal?.aborted) setLoading(false);
    }
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    void fetchWatchFindingData(controller.signal)
      .then((result) => {
        if (controller.signal.aborted) return;
        setWatches(result.watches);
        setWatchChanges(result.changes);
        setError(
          result.timelineError
            ? `Some watch findings are unavailable: ${result.timelineError}`
            : undefined,
        );
      })
      .catch((caught: unknown) => {
        if (!(caught instanceof DOMException && caught.name === 'AbortError')) {
          setError(
            caught instanceof Error ? caught.message : 'Findings failed to load.',
          );
        }
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [refreshToken]);

  const findings = useMemo(
    () =>
      buildOperationalFindings({
        watches,
        watchChanges,
        activeSnapshot,
        displayedIncidents,
        displayedCorrelations,
      }),
    [activeSnapshot, displayedCorrelations, displayedIncidents, watchChanges, watches],
  );

  async function markRead(watchId: string, changeId: string) {
    setMarkingChangeId(changeId);
    setError(undefined);
    try {
      const result = await markIncidentWatchTimelineRead(watchId, [changeId]);
      setWatchChanges((current) =>
        current.filter((change) => change.change_id !== changeId),
      );
      setWatches((current) =>
        current.map((watch) =>
          watch.watch_id === watchId
            ? {
                ...watch,
                unread_change_count: result.unread_change_count,
              }
            : watch,
        ),
      );
      onWatchDataChange?.();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Finding update failed.');
    } finally {
      setMarkingChangeId(undefined);
    }
  }

  return (
    <section className="findings-center" aria-labelledby="findings-center-heading">
      <div className="operations-heading">
        <div>
          <h3 id="findings-center-heading">Findings</h3>
          <p>Deterministic views of retained changes, coverage, and correlations.</p>
        </div>
        <button type="button" onClick={() => void load()} disabled={loading}>
          Refresh findings
        </button>
      </div>
      {loading && findings.length === 0 ? <p role="status">Loading findings…</p> : null}
      {error ? (
        <div className="assistant-error" role="alert">
          {error}
        </div>
      ) : null}
      {!loading && findings.length === 0 ? (
        <p className="findings-empty">No current findings match this view.</p>
      ) : null}
      <div className="findings-list">
        {findings.map((finding) => (
          <article
            key={finding.id}
            className={`finding finding-${finding.kind.replaceAll('_', '-')}`}
          >
            <div className="finding-heading">
              <span>{KIND_LABELS[finding.kind]}</span>
              {finding.occurredAt ? (
                <time dateTime={finding.occurredAt}>
                  {formatTime(finding.occurredAt)}
                </time>
              ) : null}
            </div>
            <strong>{finding.title}</strong>
            <p>{finding.detail}</p>
            {finding.sourceIds.length > 0 ? (
              <small>Sources: {finding.sourceIds.join(', ')}</small>
            ) : null}
            <div className="finding-actions">
              {finding.focusIncident ? (
                <button
                  type="button"
                  onClick={() =>
                    onSelectIncident(finding.focusIncident as ActiveIncident)
                  }
                  aria-label={`Focus ${finding.focusIncident.location} on map`}
                >
                  Focus on map
                </button>
              ) : null}
              {finding.kind === 'watch_change' &&
              finding.watchId &&
              finding.changeId ? (
                <button
                  type="button"
                  disabled={markingChangeId === finding.changeId}
                  onClick={() =>
                    void markRead(finding.watchId as string, finding.changeId as string)
                  }
                  aria-label={`Mark ${finding.title} read`}
                >
                  {markingChangeId === finding.changeId ? 'Marking…' : 'Mark read'}
                </button>
              ) : null}
            </div>
          </article>
        ))}
      </div>
      <p className="findings-limitation">
        Findings add no new facts, rankings, causal claims, or notifications.
      </p>
    </section>
  );
}
