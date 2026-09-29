'use client';

import { useMemo } from 'react';

import type {
  ActiveIncidentsSnapshot,
  IncidentMapRecord,
} from '@/features/incidents/model/activeIncidents';
import { assistantMapAreaOfInterest } from '@/features/map/model/assistantMapFocus';
import {
  filterCorrelationsForDisplay,
  filterIncidentsForDisplay,
  type MapLayerState,
} from '@/features/map/model/mapLayerState';
import type { ConversationMessage } from '@/shared/types/assistant';

export function useWorkspacePresentation({
  messages,
  snapshot,
  mapLayerState,
  watchFocusIncident,
  selectedIncidentId,
}: {
  messages: ConversationMessage[];
  snapshot?: ActiveIncidentsSnapshot;
  mapLayerState: MapLayerState;
  watchFocusIncident?: IncidentMapRecord;
  selectedIncidentId?: string;
}) {
  const areaOfInterest = useMemo(
    () => assistantMapAreaOfInterest(messages),
    [messages],
  );
  const commonOperationalPicture = [...messages]
    .reverse()
    .find((message) => message.report?.commonOperationalPicture)
    ?.report?.commonOperationalPicture;
  const selectedEvent = [...messages].reverse().find((message) => message.report)
    ?.report?.selectedEvent;
  const evidenceStateVersion = [...messages]
    .reverse()
    .find((message) => message.report?.decisionSupport?.evidence_state_version)?.report
    ?.decisionSupport?.evidence_state_version;
  const displayedIncidents = useMemo(
    () =>
      snapshot
        ? filterIncidentsForDisplay(
            snapshot.incidents,
            snapshot.retrieved_at,
            mapLayerState.timeWindow,
          )
        : [],
    [snapshot, mapLayerState.timeWindow],
  );
  const timeFilteredCorrelations = useMemo(
    () =>
      snapshot
        ? filterCorrelationsForDisplay(
            snapshot.correlations ?? [],
            snapshot.incidents,
            snapshot.retrieved_at,
            mapLayerState.timeWindow,
          )
        : [],
    [snapshot, mapLayerState.timeWindow],
  );
  const displayedCorrelations = useMemo(
    () =>
      mapLayerState.visibility['compound-correlations'] ? timeFilteredCorrelations : [],
    [mapLayerState.visibility, timeFilteredCorrelations],
  );
  const displayedSnapshot = useMemo(
    () =>
      snapshot
        ? {
            ...snapshot,
            incidents: displayedIncidents,
            correlations: displayedCorrelations,
          }
        : undefined,
    [snapshot, displayedIncidents, displayedCorrelations],
  );
  const mapIncidents = useMemo(
    () =>
      watchFocusIncident
        ? [
            watchFocusIncident,
            ...displayedIncidents.filter(
              (incident) => incident.event_id !== watchFocusIncident.event_id,
            ),
          ]
        : displayedIncidents,
    [watchFocusIncident, displayedIncidents],
  );
  const selectedIncident = useMemo(
    () => mapIncidents.find((incident) => incident.event_id === selectedIncidentId),
    [mapIncidents, selectedIncidentId],
  );

  return {
    areaOfInterest,
    commonOperationalPicture,
    selectedEvent,
    evidenceStateVersion,
    displayedIncidents,
    displayedCorrelations,
    displayedSnapshot,
    mapIncidents,
    selectedIncident,
  };
}
