'use client';

import { useCallback, useEffect, useRef, useState } from 'react';

import { fetchActiveIncidents } from '@/features/incidents/api/incidentsClient';
import type { ActiveIncidentsSnapshot } from '@/features/incidents/model/activeIncidents';
import {
  createRefreshController,
  REFRESH_POLICIES,
  type RefreshController,
} from '@/shared/model/refreshPolicy';

export type ActiveIncidentsStatus = 'loading' | 'success' | 'error';

function errorMessage(caught: unknown): string {
  return caught instanceof Error
    ? caught.message
    : 'Active incidents could not be loaded.';
}

export function useActiveIncidents() {
  const [snapshot, setSnapshot] = useState<ActiveIncidentsSnapshot>();
  const [status, setStatus] = useState<ActiveIncidentsStatus>('loading');
  const [error, setError] = useState<string>();
  const refreshController = useRef<RefreshController | undefined>(undefined);

  const load = useCallback(async (signal: AbortSignal) => {
    setStatus('loading');
    setError(undefined);
    try {
      const nextSnapshot = await fetchActiveIncidents({ signal });
      if (signal.aborted) return;
      setSnapshot(nextSnapshot);
      setStatus('success');
    } catch (caught) {
      if (signal.aborted) return;
      setError(errorMessage(caught));
      setStatus('error');
    }
  }, []);

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

  return { snapshot, status, error, refresh };
}
