'use client';

import { useCallback, useEffect, useRef, useState } from 'react';

import { fetchActiveIncidents } from '@/features/incidents/api/incidentsClient';
import type { ActiveIncidentsSnapshot } from '@/features/incidents/model/activeIncidents';

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
  const activeRequest = useRef<AbortController | undefined>(undefined);

  const refresh = useCallback(async () => {
    activeRequest.current?.abort();
    const controller = new AbortController();
    activeRequest.current = controller;
    setStatus('loading');
    setError(undefined);
    try {
      const nextSnapshot = await fetchActiveIncidents({ signal: controller.signal });
      if (controller.signal.aborted) return;
      setSnapshot(nextSnapshot);
      setStatus('success');
    } catch (caught) {
      if (controller.signal.aborted) return;
      setError(errorMessage(caught));
      setStatus('error');
    }
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    activeRequest.current = controller;
    void fetchActiveIncidents({ signal: controller.signal })
      .then((nextSnapshot) => {
        if (controller.signal.aborted) return;
        setSnapshot(nextSnapshot);
        setStatus('success');
      })
      .catch((caught: unknown) => {
        if (controller.signal.aborted) return;
        setError(errorMessage(caught));
        setStatus('error');
      });
    return () => controller.abort();
  }, []);

  return { snapshot, status, error, refresh };
}
