'use client';

import { useCallback, useEffect, useRef, useState } from 'react';

import {
  createGroundImageryRequest,
  fetchGroundImageryReadiness,
  fetchGroundImageryRequest,
  prepareGroundImagerySelection,
  replaceGroundImageryRegion,
  refreshGroundImageryRequest,
  setGroundImageryWatch,
} from '@/features/imagery/api/groundImageryClient';
import type {
  GroundImageryPanelReadiness,
  GroundImageryPanelRequest,
} from '@/features/imagery/model/groundImagery';
import type {
  GroundImageryRegionRequest,
  GroundImagerySelectionResponse,
} from '@/shared/api/generated/assistant';

type LoadState = 'idle' | 'loading' | 'ready' | 'error';
const SLOW_SEARCH_DELAY_MS = 8_000;
const PREPARATION_POLL_MS = 3_000;
const WATCH_POLL_MS = 30_000;

export function useGroundImageryWorkflow(
  incidentId: string,
  monitoringAvailable = false,
) {
  const [request, setRequest] = useState<GroundImageryPanelRequest>();
  const [readiness, setReadiness] = useState<GroundImageryPanelReadiness>();
  const [loadState, setLoadState] = useState<LoadState>('idle');
  const [searchIsSlow, setSearchIsSlow] = useState(false);
  const [error, setError] = useState<string>();
  const [action, setAction] = useState<string>();
  const requestVersion = useRef(0);

  const load = useCallback(
    async (signal?: AbortSignal) => {
      const version = ++requestVersion.current;
      setLoadState('loading');
      setRequest(undefined);
      setReadiness(undefined);
      setSearchIsSlow(false);
      setError(undefined);
      setAction(undefined);
      try {
        const [, nextRequest] = await Promise.all([
          fetchGroundImageryReadiness(signal).then((nextReadiness) => {
            if (!signal?.aborted && version === requestVersion.current)
              setReadiness(nextReadiness);
            return nextReadiness;
          }),
          createGroundImageryRequest(incidentId, signal),
        ]);
        if (signal?.aborted || version !== requestVersion.current) return;
        setRequest(nextRequest);
        setLoadState('ready');
      } catch (loadError) {
        if (signal?.aborted || version !== requestVersion.current) return;
        setError(
          loadError instanceof Error ? loadError.message : 'Ground view failed.',
        );
        setLoadState('error');
      }
    },
    [incidentId],
  );

  useEffect(() => {
    const controller = new AbortController();
    void fetchGroundImageryReadiness(controller.signal)
      .then((next) => {
        if (!controller.signal.aborted) setReadiness(next);
      })
      .catch((caught: unknown) => {
        if (!controller.signal.aborted)
          setError(
            caught instanceof Error
              ? caught.message
              : 'Imagery availability is unknown.',
          );
      });
    return () => {
      controller.abort();
      requestVersion.current += 1;
    };
  }, [incidentId]);

  useEffect(() => {
    if (loadState !== 'loading') return;
    const timer = window.setTimeout(() => setSearchIsSlow(true), SLOW_SEARCH_DELAY_MS);
    return () => window.clearTimeout(timer);
  }, [loadState]);

  useEffect(() => {
    if (
      !request ||
      (request.state !== 'queued' && !(request.watch_enabled && monitoringAvailable))
    )
      return;
    const controller = new AbortController();
    const version = requestVersion.current;
    const pollInterval =
      request.state === 'queued' ? PREPARATION_POLL_MS : WATCH_POLL_MS;
    let timer: number;
    const poll = async () => {
      try {
        const nextRequest = await fetchGroundImageryRequest(
          request.request_id,
          controller.signal,
        );
        if (controller.signal.aborted || version !== requestVersion.current) return;
        setRequest(nextRequest);
      } catch {
        if (!controller.signal.aborted && version === requestVersion.current) {
          timer = window.setTimeout(() => void poll(), pollInterval);
        }
      }
    };
    timer = window.setTimeout(() => void poll(), pollInterval);
    return () => {
      controller.abort();
      window.clearTimeout(timer);
    };
  }, [request, monitoringAvailable]);

  const runAction = useCallback(
    async (name: string, operation: () => Promise<GroundImageryPanelRequest>) => {
      const version = requestVersion.current;
      setAction(name);
      setError(undefined);
      try {
        const nextRequest = await operation();
        if (version === requestVersion.current) setRequest(nextRequest);
      } catch (actionError) {
        if (version === requestVersion.current) {
          setError(
            actionError instanceof Error
              ? actionError.message
              : 'Ground view action failed.',
          );
        }
      } finally {
        if (version === requestVersion.current) setAction(undefined);
      }
    },
    [],
  );

  const handleRefresh = () => {
    if (!request) return;
    void runAction('refresh', () => refreshGroundImageryRequest(request.request_id));
  };

  const handleRegion = (region: GroundImageryRegionRequest['region']) => {
    if (!request) return;
    void runAction('region', () =>
      replaceGroundImageryRegion(request.request_id, region),
    );
  };

  const handleWatch = () => {
    if (!request) return;
    void runAction('watch', () =>
      setGroundImageryWatch(request.request_id, !request.watch_enabled),
    );
  };

  const handlePrepare = (selection: GroundImagerySelectionResponse) => {
    if (!request || !selection.observation) return;
    void runAction(`prepare:${selection.selection_id}`, () =>
      prepareGroundImagerySelection(request.request_id, {
        sensor: selection.sensor,
        role: selection.role,
        overview: true,
      }),
    );
  };

  return {
    request,
    readiness,
    loadState,
    searchIsSlow,
    error,
    action,
    load,
    handleRefresh,
    handleRegion,
    handleWatch,
    handlePrepare,
  };
}
