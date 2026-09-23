'use client';

import { useCallback, useEffect, useRef, useState } from 'react';

import { fetchActiveIncidents } from '@/features/incidents/api/incidentsClient';
import type {
  ActiveIncident,
  ActiveIncidentsSnapshot,
  DisasterType,
  IncidentView,
} from '@/features/incidents/model/activeIncidents';
import { matchesApiSchema } from '@/shared/api/generated/assistant';
import { HttpResponseError } from '@/shared/api/http';
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
    const parsed: unknown = JSON.parse(value);
    if (!matchesApiSchema('ActiveIncidentsSnapshotResponse', parsed)) {
      return undefined;
    }
    return { ...(parsed as ActiveIncidentsSnapshot), availability: 'offline-cache' };
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

function incidentIdentity(incident: ActiveIncident): string {
  return [
    incident.event_id,
    incident.physical_event_id ?? '',
    incident.source.source_id,
    incident.observation_kind ?? '',
  ].join('|');
}

function appendUnique(
  current: ActiveIncident[],
  incoming: ActiveIncident[],
): ActiveIncident[] {
  const seen = new Set(current.map(incidentIdentity));
  return [
    ...current,
    ...incoming.filter((item) => {
      const identity = incidentIdentity(item);
      if (seen.has(identity)) return false;
      seen.add(identity);
      return true;
    }),
  ];
}

export function useActiveIncidents() {
  const [snapshotState, setSnapshotState] = useState<{
    key: string;
    version: number;
    value: ActiveIncidentsSnapshot;
  }>();
  const [status, setStatus] = useState<ActiveIncidentsStatus>('loading');
  const [error, setError] = useState<string>();
  const [search, setSearch] = useState('');
  const [appliedSearch, setAppliedSearch] = useState('');
  const [view, setView] = useState<IncidentView>('recent');
  const [hazard, setHazard] = useState<DisasterType | undefined>();
  const [occurrenceStart, setOccurrenceStart] = useState('');
  const [occurrenceEnd, setOccurrenceEnd] = useState('');
  const [loadingPageKey, setLoadingPageKey] = useState<string | null>(null);
  const refreshController = useRef<RefreshController | undefined>(undefined);
  const pageController = useRef<AbortController | null>(null);
  const pageLoading = useRef(false);
  const version = useRef(0);
  const queryKey = cacheKey(
    view,
    hazard,
    appliedSearch,
    occurrenceStart,
    occurrenceEnd,
  );
  const queryKeyRef = useRef(queryKey);
  const loadingMore = loadingPageKey === queryKey;
  const snapshot = snapshotState?.key === queryKey ? snapshotState.value : undefined;

  useEffect(() => {
    const timer = setTimeout(() => setAppliedSearch(search.trim()), 250);
    return () => clearTimeout(timer);
  }, [search]);

  const load = useCallback(
    async (signal: AbortSignal) => {
      setStatus('loading');
      setError(undefined);
      try {
        const key = queryKey;
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
        pageController.current?.abort();
        pageLoading.current = false;
        setLoadingPageKey(null);
        const liveSnapshot = { ...nextSnapshot, availability: 'live' as const };
        setSnapshotState({ key, version: ++version.current, value: liveSnapshot });
        writeCachedSnapshot(key, liveSnapshot);
        setStatus('success');
      } catch (caught) {
        if (signal.aborted) return;
        if (caught instanceof HttpResponseError && caught.status < 500) {
          setError(errorMessage(caught));
          setStatus('error');
          return;
        }
        const cached = readCachedSnapshot(queryKey);
        if (cached) {
          setSnapshotState({
            key: queryKey,
            version: ++version.current,
            value: cached,
          });
          setError(
            `Showing the last successful snapshot; data is stale. ${errorMessage(caught)}`,
          );
          setStatus('offline');
          return;
        }
        setError(errorMessage(caught));
        setStatus('error');
      }
    },
    [appliedSearch, hazard, occurrenceEnd, occurrenceStart, queryKey, view],
  );

  useEffect(() => {
    queryKeyRef.current = queryKey;
    pageController.current?.abort();
    pageLoading.current = false;
    const controller = createRefreshController(
      REFRESH_POLICIES['active-incidents'],
      load,
      document,
    );
    refreshController.current = controller;
    controller.start();
    return () => {
      controller.stop();
      pageController.current?.abort();
      refreshController.current = undefined;
    };
  }, [load, queryKey]);

  const refresh = useCallback(
    () => refreshController.current?.refreshNow() ?? Promise.resolve(),
    [],
  );

  const loadMore = useCallback(async () => {
    const cursor = snapshot?.next_cursor;
    if (
      !cursor ||
      pageLoading.current ||
      !snapshotState ||
      snapshotState.key !== queryKey
    )
      return;
    const pageVersion = snapshotState.version;
    const pageSnapshotVersion = snapshot.snapshot_version;
    const controller = new AbortController();
    pageController.current = controller;
    pageLoading.current = true;
    setLoadingPageKey(queryKey);
    try {
      const nextSnapshot = await fetchActiveIncidents({
        pageSize: 20,
        view: view === 'recent' ? undefined : view,
        hazard,
        search: appliedSearch || undefined,
        occurrenceStart: view === 'historical' ? utcInput(occurrenceStart) : undefined,
        occurrenceEnd: view === 'historical' ? utcInput(occurrenceEnd) : undefined,
        cursor,
        signal: controller.signal,
      });
      if (controller.signal.aborted || queryKeyRef.current !== queryKey) return;
      if (
        pageSnapshotVersion &&
        nextSnapshot.snapshot_version !== pageSnapshotVersion
      ) {
        setError('Incident snapshot changed. Refresh to load the current pages.');
        return;
      }
      setSnapshotState((current) => {
        if (!current || current.key !== queryKey || current.version !== pageVersion)
          return current;
        const correlationIds = new Set(
          (current.value.correlations ?? []).map((item) => item.correlation_id),
        );
        return {
          ...current,
          value: {
            ...current.value,
            incidents: appendUnique(current.value.incidents, nextSnapshot.incidents),
            observations: appendUnique(
              current.value.observations ?? [],
              nextSnapshot.observations ?? [],
            ),
            correlations: [
              ...(current.value.correlations ?? []),
              ...(nextSnapshot.correlations ?? []).filter(
                (item) => !correlationIds.has(item.correlation_id),
              ),
            ],
            next_cursor: nextSnapshot.next_cursor,
            has_more: nextSnapshot.has_more,
            total_incident_count: nextSnapshot.total_incident_count,
          },
        };
      });
    } catch (caught) {
      if (!controller.signal.aborted && queryKeyRef.current === queryKey)
        setError(errorMessage(caught));
    } finally {
      if (pageController.current === controller) {
        pageController.current = null;
        pageLoading.current = false;
        setLoadingPageKey(null);
      }
    }
  }, [
    appliedSearch,
    hazard,
    occurrenceEnd,
    occurrenceStart,
    snapshot,
    snapshotState,
    queryKey,
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
