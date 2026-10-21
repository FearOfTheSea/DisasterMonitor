'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';

import { fetchActiveIncident } from '@/features/incidents/api/incidentsClient';
import type { IncidentMapRecord } from '@/features/incidents/model/activeIncidents';

export function matchesIncidentIdentifier(
  incident: IncidentMapRecord,
  identifier: string,
): boolean {
  return (
    incident.event_id === identifier ||
    // Old bookmarks retain a local extraction ID and a separate scan URL. Only
    // records from that loaded scan may translate it to an inspection reference.
    (identifier.startsWith('discovery:') &&
      incident.event_id.replace(
        /^discovery:[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}:/i,
        '',
      ) === identifier) ||
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
  const [resolvedLocations, setResolvedLocations] = useState<IncidentMapRecord[]>([]);
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
  const lookupIdentifier = local?.event_id ?? identifier;
  useEffect(() => {
    if (!lookupIdentifier) return;
    const controller = new AbortController();
    fetchActiveIncident(lookupIdentifier, controller.signal)
      .then((incident) => {
        if (!controller.signal.aborted) {
          setLookup({ identifier: lookupIdentifier, incident });
          if (incident.geometry) {
            setResolvedLocations((current) => [
              ...current
                .filter((item) => item.event_id !== incident.event_id)
                .slice(-63),
              incident,
            ]);
          }
        }
      })
      .catch((error: unknown) => {
        if (!controller.signal.aborted)
          setLookup((current) => ({
            identifier: lookupIdentifier,
            incident:
              current?.identifier === lookupIdentifier ? current.incident : undefined,
            error:
              error instanceof Error
                ? error.message
                : 'Incident lookup is unavailable.',
          }));
      });
    return () => controller.abort();
  }, [lookupIdentifier]);
  const retained = lookup?.identifier === lookupIdentifier ? lookup : undefined;
  const withResolvedLocation = useCallback(
    (record: IncidentMapRecord) => {
      if (record.geometry) return record;
      const resolved = resolvedLocations.find(
        (item) =>
          item.event_id === record.event_id &&
          item.event_time === record.event_time &&
          item.source.canonical_url === record.source.canonical_url,
      );
      return resolved
        ? {
            ...record,
            geometry: resolved.geometry,
            evidence_sources: resolved.evidence_sources,
            discovery_reports: resolved.discovery_reports,
            collection_notices: resolved.collection_notices,
          }
        : record;
    },
    [resolvedLocations],
  );
  const incident = useMemo(
    () => (local ? withResolvedLocation(local) : retained?.incident),
    [local, retained?.incident, withResolvedLocation],
  );
  return {
    incident,
    withResolvedLocation,
    error: retained?.error,
    loading: Boolean(identifier && !local && !retained),
  };
}
