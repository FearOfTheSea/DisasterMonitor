'use client';

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  fetchDiscoveryScan,
  requestDiscoveryScan,
  reprocessDiscoveryScan,
  type ReportingDays,
} from '@/features/incidents/api/discoveryClient';
import type {
  ActiveIncidentsSnapshot,
  DisasterType,
} from '@/features/incidents/model/activeIncidents';
import type { DiscoveryScanResponse } from '@/shared/api/generated/assistant';

export function useDiscoveryScan() {
  const [days, setDays] = useState<ReportingDays>(7);
  const [run, setRun] = useState<DiscoveryScanResponse>();
  const [error, setError] = useState<string>();
  const [submitting, setSubmitting] = useState(false);
  const [search, setSearch] = useState('');
  const [hazard, setHazard] = useState<DisasterType>();
  const controller = useRef<AbortController | undefined>(undefined);
  const id = run?.scan_id;
  const running = run?.status === 'running';

  useEffect(() => () => controller.current?.abort(), []);

  useEffect(() => {
    const retainedId = new URLSearchParams(window.location.search).get('scan');
    if (
      !retainedId ||
      !/^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/i.test(retainedId)
    )
      return;
    const restoring = new AbortController();
    controller.current = restoring;
    void fetchDiscoveryScan(
      retainedId,
      AbortSignal.any([restoring.signal, AbortSignal.timeout(20_000)]),
    )
      .then((value) => {
        if (restoring.signal.aborted) return;
        setRun(value);
        setDays(value.reporting_days as ReportingDays);
      })
      .catch(() => {
        if (!restoring.signal.aborted)
          setError(
            'The retained scan could not be restored. Start a new scan or browse provider catalogs.',
          );
      });
    return () => restoring.abort();
  }, []);

  useEffect(() => {
    if (!id || !running) return;
    const polling = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      try {
        const next = await fetchDiscoveryScan(
          id,
          AbortSignal.any([polling.signal, AbortSignal.timeout(20_000)]),
        );
        if (polling.signal.aborted) return;
        setRun(next);
        setError(undefined);
        if (next.status !== 'running') return;
      } catch (caught) {
        if (polling.signal.aborted) return;
        setError(
          `Scan status could not be refreshed; available results retained. ${caught instanceof Error ? caught.message : ''}`,
        );
      }
      timer = setTimeout(() => void poll(), 2000);
    };
    timer = setTimeout(() => void poll(), 500);
    return () => {
      polling.abort();
      clearTimeout(timer);
    };
  }, [id, running]);

  const update = useCallback(
    async (request: (signal: AbortSignal) => Promise<DiscoveryScanResponse>) => {
      controller.current?.abort();
      const nextController = new AbortController();
      controller.current = nextController;
      setSubmitting(true);
      setError(undefined);
      try {
        const next = await request(
          AbortSignal.any([nextController.signal, AbortSignal.timeout(20_000)]),
        );
        if (!nextController.signal.aborted) {
          setRun(next);
          const url = new URL(window.location.href);
          url.searchParams.set('scan', next.scan_id);
          window.history.replaceState(null, '', url);
          setSearch('');
          setHazard(undefined);
        }
      } catch (caught) {
        if (!nextController.signal.aborted)
          setError(caught instanceof Error ? caught.message : 'Scan could not start.');
      } finally {
        if (!nextController.signal.aborted) setSubmitting(false);
      }
    },
    [],
  );

  const start = useCallback(
    () => update((signal) => requestDiscoveryScan(days, signal)),
    [days, update],
  );
  const reprocess = useCallback(async () => {
    if (id) await update((signal) => reprocessDiscoveryScan(id, signal));
  }, [id, update]);

  const snapshot = useMemo(() => {
    if (!run) return undefined;
    const value = run.snapshot as ActiveIncidentsSnapshot;
    const query = search.trim().toLowerCase();
    return {
      ...value,
      publication_scan: true,
      scan_status: run.status,
      incidents: value.incidents.filter(
        (item) =>
          (!hazard || item.disaster === hazard) &&
          (!query ||
            `${item.location} ${item.source.title} ${item.source.publisher} ${(item.discovery_reports ?? []).map((report) => `${report.mention_excerpt ?? ''} ${report.location ?? ''} ${report.event_date_wording ?? ''}`).join(' ')}`
              .toLowerCase()
              .includes(query)),
      ),
    };
  }, [run, search, hazard]);
  return {
    days,
    setDays,
    run,
    snapshot,
    error,
    submitting,
    start,
    reprocess,
    search,
    setSearch,
    hazard,
    setHazard,
    clear: () => {
      controller.current?.abort();
      setSubmitting(false);
      setRun(undefined);
      const url = new URL(window.location.href);
      url.searchParams.delete('scan');
      window.history.replaceState(null, '', url);
    },
  };
}
