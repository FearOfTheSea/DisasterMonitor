'use client';

import { useCallback, useEffect, useRef, useState } from 'react';

import { fetchActiveIncidents } from '@/features/incidents/api/incidentsClient';
import type {
  ActiveIncidentsSnapshot,
  DisasterType,
  IncidentView,
} from '@/features/incidents/model/activeIncidents';
import {
  createRefreshController,
  REFRESH_POLICIES,
  type RefreshController,
} from '@/shared/model/refreshPolicy';

export type ActiveIncidentsStatus = 'loading' | 'success' | 'offline' | 'error';

const SNAPSHOT_CACHE_PREFIX = 'disaster-monitor:last-snapshot:v1:';

function cacheKey(
  view: IncidentView,
  hazard?: DisasterType,
  search = '',
  occurrenceStart = '',
  occurrenceEnd = '',
): string {
  const base = `${SNAPSHOT_CACHE_PREFIX}${view}:${hazard ?? 'all'}:${search}`;
  return occurrenceStart || occurrenceEnd
    ? `${base}:${occurrenceStart}:${occurrenceEnd}`
    : base;
}

function utcInput(value: string): string | undefined {
  return value ? new Date(`${value}:00Z`).toISOString() : undefined;
}

function readCachedSnapshot(key: string): ActiveIncidentsSnapshot | undefined {
  try {
    const value = window.localStorage.getItem(key);
    if (!value || value.length > 2_000_000) return undefined;
    const parsed = JSON.parse(value) as ActiveIncidentsSnapshot;
    if (
      typeof parsed.retrieved_at !== 'string' ||
      !Array.isArray(parsed.incidents) ||
      !Array.isArray(parsed.coverage) ||
      !Array.isArray(parsed.warnings)
    ) {
      return undefined;
    }
    return { ...parsed, availability: 'offline-cache' };
  } catch {
    return undefined;
  }
}

function writeCachedSnapshot(key: string, snapshot: ActiveIncidentsSnapshot): void {
  try {
    window.localStorage.setItem(
      key,
      JSON.stringify({
        ...snapshot,
        availability: 'live',
        cached_at: new Date().toISOString(),
      }),
    );
  } catch {
    // Storage can be unavailable or full; live operation remains usable.
  }
}

function errorMessage(caught: unknown): string {
  return caught instanceof Error
    ? caught.message
    : 'Active incidents could not be loaded.';
}

export function useActiveIncidents() {
  const [snapshot, setSnapshot] = useState<ActiveIncidentsSnapshot>();
  const [status, setStatus] = useState<ActiveIncidentsStatus>('loading');
  const [error, setError] = useState<string>();
  const [search, setSearch] = useState('');
  const [appliedSearch, setAppliedSearch] = useState('');
  const [view, setView] = useState<IncidentView>('recent');
  const [hazard, setHazard] = useState<DisasterType | undefined>();
  const [occurrenceStart, setOccurrenceStart] = useState('');
  const [occurrenceEnd, setOccurrenceEnd] = useState('');
  const [loadingMore, setLoadingMore] = useState(false);
  const refreshController = useRef<RefreshController | undefined>(undefined);

  useEffect(() => {
    const timer = setTimeout(() => setAppliedSearch(search.trim()), 250);
    return () => clearTimeout(timer);
  }, [search]);

  const load = useCallback(
    async (signal: AbortSignal) => {
      setStatus('loading');
      setError(undefined);
      try {
        const key = cacheKey(
          view,
          hazard,
          appliedSearch,
          occurrenceStart,
          occurrenceEnd,
        );
        const nextSnapshot = await fetchActiveIncidents({
          pageSize: 20,
          view: view === 'recent' ? undefined : view,
          hazard,
          search: appliedSearch || undefined,
          occurrenceStart:
            view === 'historical' ? utcInput(occurrenceStart) : undefined,
          occurrenceEnd: view === 'historical' ? utcInput(occurrenceEnd) : undefined,
          signal,
        });
        if (signal.aborted) return;
        const liveSnapshot = { ...nextSnapshot, availability: 'live' as const };
        setSnapshot(liveSnapshot);
        writeCachedSnapshot(key, liveSnapshot);
        setStatus('success');
      } catch (caught) {
        if (signal.aborted) return;
        const cached = readCachedSnapshot(
          cacheKey(view, hazard, appliedSearch, occurrenceStart, occurrenceEnd),
        );
        if (cached) {
          setSnapshot(cached);
          setError(
            'Network unavailable. Showing the last successful snapshot; data is stale.',
          );
          setStatus('offline');
          return;
        }
        setError(errorMessage(caught));
        setStatus('error');
      }
    },
    [appliedSearch, hazard, occurrenceEnd, occurrenceStart, view],
  );

  useEffect(() => {
    const controller = createRefreshController(
      REFRESH_POLICIES['active-incidents'],
      load,
      document,
    );
    refreshController.current = controller;
    controller.start();
    return () => {
      controller.stop();
      refreshController.current = undefined;
    };
  }, [load]);

  const refresh = useCallback(
    () => refreshController.current?.refreshNow() ?? Promise.resolve(),
    [],
  );

  const loadMore = useCallback(async () => {
    const cursor = snapshot?.next_cursor;
    if (!cursor || loadingMore) return;
    setLoadingMore(true);
    try {
      const nextSnapshot = await fetchActiveIncidents({
        pageSize: 20,
        view: view === 'recent' ? undefined : view,
        hazard,
        search: appliedSearch || undefined,
        occurrenceStart: view === 'historical' ? utcInput(occurrenceStart) : undefined,
        occurrenceEnd: view === 'historical' ? utcInput(occurrenceEnd) : undefined,
        cursor,
      });
      setSnapshot((current) => {
        if (!current) return nextSnapshot;
        const incidentIds = new Set(current.incidents.map((item) => item.event_id));
        const observationIds = new Set(
          (current.observations ?? []).map((item) => item.event_id),
        );
        const correlationIds = new Set(
          (current.correlations ?? []).map((item) => item.correlation_id),
        );
        return {
          ...current,
          incidents: [
            ...current.incidents,
            ...nextSnapshot.incidents.filter((item) => !incidentIds.has(item.event_id)),
          ],
          observations: [
            ...(current.observations ?? []),
            ...(nextSnapshot.observations ?? []).filter(
              (item) => !observationIds.has(item.event_id),
            ),
          ],
          correlations: [
            ...(current.correlations ?? []),
            ...(nextSnapshot.correlations ?? []).filter(
              (item) => !correlationIds.has(item.correlation_id),
            ),
          ],
          next_cursor: nextSnapshot.next_cursor,
          has_more: nextSnapshot.has_more,
          total_incident_count: nextSnapshot.total_incident_count,
        };
      });
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setLoadingMore(false);
    }
  }, [
    appliedSearch,
    hazard,
    loadingMore,
    occurrenceEnd,
    occurrenceStart,
    snapshot?.next_cursor,
    view,
  ]);

  return {
    snapshot,
    status,
    error,
    refresh,
    search,
    setSearch,
    view,
    setView,
    hazard,
    setHazard,
    occurrenceStart,
    setOccurrenceStart,
    occurrenceEnd,
    setOccurrenceEnd,
    loadMore,
    loadingMore,
  };
}
