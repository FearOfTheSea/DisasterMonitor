'use client';

import { useEffect, useMemo, useState } from 'react';

import { fetchActiveIncident } from '@/features/incidents/api/incidentsClient';
import type { IncidentMapRecord } from '@/features/incidents/model/activeIncidents';

export function matchesIncidentIdentifier(
  incident: IncidentMapRecord,
  identifier: string,
): boolean {
  return (
    incident.event_id === identifier ||
    incident.physical_event_id === identifier ||
    incident.provider_ids.some(
      (alias) => !alias.startsWith('glide:') && alias === identifier,
    )
  );
}

export function useIncidentSelection(
  identifier: string | undefined,
  records: IncidentMapRecord[],
) {
  const local = useMemo(
    () =>
      identifier
        ? records.find((item) => matchesIncidentIdentifier(item, identifier))
        : undefined,
    [identifier, records],
  );
  const [lookup, setLookup] = useState<{
    identifier: string;
    incident?: IncidentMapRecord;
    error?: string;
  }>();
  useEffect(() => {
    if (!identifier) return;
    const controller = new AbortController();
    fetchActiveIncident(identifier, controller.signal)
      .then((incident) => {
        if (!controller.signal.aborted) setLookup({ identifier, incident });
      })
      .catch((error: unknown) => {
        if (!controller.signal.aborted)
          setLookup((current) => ({
            identifier,
            incident: current?.identifier === identifier ? current.incident : undefined,
            error:
              error instanceof Error
                ? error.message
                : 'Incident lookup is unavailable.',
          }));
      });
    return () => controller.abort();
  }, [identifier]);
  const retained = lookup?.identifier === identifier ? lookup : undefined;
  return {
    incident: local ?? retained?.incident,
    error: retained?.error,
    loading: Boolean(identifier && !local && !retained),
  };
}
