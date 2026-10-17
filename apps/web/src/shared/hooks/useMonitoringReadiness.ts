'use client';

import { useEffect, useState } from 'react';
import { fetchMonitoringReadiness } from '@/shared/api/monitoringClient';
import type { MonitoringReadinessResponse } from '@/shared/api/generated/assistant';

export function useMonitoringReadiness() {
  const [readiness, setReadiness] = useState<MonitoringReadinessResponse>();
  const [error, setError] = useState<string>();
  useEffect(() => {
    const controller = new AbortController();
    fetchMonitoringReadiness(controller.signal)
      .then((value) => {
        if (!controller.signal.aborted) setReadiness(value);
      })
      .catch((caught: unknown) => {
        if (!controller.signal.aborted)
          setError(
            caught instanceof Error
              ? caught.message
              : 'Monitoring availability is unknown.',
          );
      });
    return () => controller.abort();
  }, []);
  return {
    available: Boolean(
      readiness?.durable_storage && readiness.scheduler_worker_configured,
    ),
    detail: readiness?.detail ?? error ?? 'Checking scheduled monitoring availability…',
  };
}
