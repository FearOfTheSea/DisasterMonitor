'use client';

import { useCallback, useEffect, useRef, useState } from 'react';

import { fetchWeatherAlerts } from '@/features/weather/api/weatherAlertsClient';
import type { WeatherAlertsSnapshot } from '@/features/weather/model/weatherAlert';
import {
  createRefreshController,
  REFRESH_POLICIES,
  type RefreshController,
} from '@/shared/model/refreshPolicy';

export function useWeatherAlerts() {
  const [snapshot, setSnapshot] = useState<WeatherAlertsSnapshot>();
  const [status, setStatus] = useState<'loading' | 'success' | 'error'>('loading');
  const [error, setError] = useState<string>();
  const controller = useRef<RefreshController | undefined>(undefined);
  const load = useCallback(async (signal: AbortSignal) => {
    try {
      const next = await fetchWeatherAlerts(signal);
      if (signal.aborted) return;
      setSnapshot(next);
      setStatus('success');
      setError(undefined);
    } catch (caught) {
      if (signal.aborted) return;
      setStatus('error');
      setError(caught instanceof Error ? caught.message : 'Weather alerts failed.');
    }
  }, []);

  useEffect(() => {
    const next = createRefreshController(
      REFRESH_POLICIES['weather-alerts'],
      load,
      document,
    );
    controller.current = next;
    next.start();
    return () => {
      next.stop();
      controller.current = undefined;
    };
  }, [load]);

  return {
    snapshot,
    status,
    error,
    refresh: () => controller.current?.refreshNow() ?? Promise.resolve(),
  };
}
