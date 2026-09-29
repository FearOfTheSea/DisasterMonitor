'use client';

import {
  useCallback,
  useMemo,
  useState,
  type Dispatch,
  type SetStateAction,
} from 'react';

import type { useAssistantConversation } from '@/features/assistant/hooks/useAssistantConversation';
import { executeAutomaticOperatorActions } from '@/features/assistant/model/operatorActions';
import {
  buildCommandRegistry,
  type CommandRegistryContext,
} from '@/features/commands/model/commandRegistry';
import type { IncidentMapRecord } from '@/features/incidents/model/activeIncidents';
import { relatedInvestigation } from '@/features/incidents/ui/incidentPresentation';
import type { MapLayerState } from '@/features/map/model/mapLayerState';
import type { RegionalPresetId } from '@/features/map/model/regionalPresets';
import type { MapView } from '@/shared/types/assistant';

import type { useWorkspaceNavigation } from './useWorkspaceNavigation';

type Navigation = ReturnType<typeof useWorkspaceNavigation>;
const EMPTY_INCIDENTS: CommandRegistryContext['incidents'] = [];

type WorkspaceActionInputs = {
  submit: ReturnType<typeof useAssistantConversation>['submit'];
  mapView: MapView;
  mapLayerState: MapLayerState;
  setMapLayerState: Dispatch<SetStateAction<MapLayerState>>;
  incidents?: CommandRegistryContext['incidents'];
  selectedIncidentId?: string;
  selectedIncident?: IncidentMapRecord;
  selectActiveIncident: (incidentId: string) => void;
  selectWatchIncident: (incident: IncidentMapRecord) => void;
  clearSelectedIncident: () => void;
  setFocusRequestToken: Dispatch<SetStateAction<number>>;
  selectRegion: (region: RegionalPresetId) => void;
  navigate: Navigation['navigate'];
  openPane: Navigation['openPane'];
  openSection: Navigation['openSection'];
};

export function useWorkspaceActions({
  submit,
  mapView,
  mapLayerState,
  setMapLayerState,
  incidents,
  selectedIncidentId,
  selectedIncident,
  selectActiveIncident,
  selectWatchIncident: selectWatchOnMap,
  clearSelectedIncident,
  setFocusRequestToken,
  selectRegion,
  navigate,
  openPane,
  openSection,
}: WorkspaceActionInputs) {
  const [assistantDraft, setAssistantDraft] = useState('');
  const [assistantFocusToken, setAssistantFocusToken] = useState(0);
  const commandIncidents = incidents ?? EMPTY_INCIDENTS;

  const openOperationsAt = useCallback(
    (headingId?: string) => {
      openSection(headingId === 'findings-center-heading' ? 'activity' : 'watches');
    },
    [openSection],
  );
  const openSourceCatalog = useCallback(() => navigate('sources'), [navigate]);
  const selectIncident = useCallback(
    (incidentId: string) => {
      selectActiveIncident(incidentId);
      openPane('ground', incidentId);
    },
    [selectActiveIncident, openPane],
  );
  const selectWatchIncident = useCallback(
    (incident: IncidentMapRecord) => {
      selectWatchOnMap(incident);
      openPane('ground', incident.event_id);
    },
    [selectWatchOnMap, openPane],
  );
  const submitQuestion = useCallback(
    async (question: string) => {
      const response = await submit(question, mapView);
      if (!response) return false;
      const execution = executeAutomaticOperatorActions(
        response.operator_actions ?? [],
        mapLayerState,
      );
      setMapLayerState(execution.mapLayerState);
      for (const panel of execution.openPanels) {
        if (panel === 'sources') openSourceCatalog();
        else if (panel === 'findings') openOperationsAt('findings-center-heading');
        else openOperationsAt();
      }
      return true;
    },
    [
      submit,
      mapView,
      mapLayerState,
      setMapLayerState,
      openSourceCatalog,
      openOperationsAt,
    ],
  );
  const commands = useMemo(
    () =>
      buildCommandRegistry({
        incidents: commandIncidents,
        layerState: mapLayerState,
        selectedIncidentId,
        onSelectIncident: selectIncident,
        onFocusSelectedIncident: () => setFocusRequestToken((current) => current + 1),
        onSelectRegion: selectRegion,
        onLayerStateChange: setMapLayerState,
        onOpenFindings: () => openOperationsAt('findings-center-heading'),
        onOpenSourceCatalog: openSourceCatalog,
        onOpenIncidentWatches: () => openOperationsAt('incident-watches-heading'),
        onOpenOperations: () => openOperationsAt(),
      } satisfies CommandRegistryContext),
    [
      commandIncidents,
      mapLayerState,
      selectedIncidentId,
      selectIncident,
      setFocusRequestToken,
      selectRegion,
      setMapLayerState,
      openOperationsAt,
      openSourceCatalog,
    ],
  );
  const closeEvent = useCallback(() => {
    clearSelectedIncident();
    openPane(null, null);
  }, [clearSelectedIncident, openPane]);
  const closeAssistant = useCallback(
    () => openPane(selectedIncident ? 'event' : null),
    [openPane, selectedIncident],
  );
  const askAboutEvent = useCallback(() => {
    if (selectedIncident) {
      setAssistantDraft(relatedInvestigation(selectedIncident).question);
      setAssistantFocusToken((current) => current + 1);
    }
    openPane('assistant');
  }, [selectedIncident, openPane]);

  return {
    assistantDraft,
    setAssistantDraft,
    assistantFocusToken,
    commands,
    selectIncident,
    selectWatchIncident,
    submitQuestion,
    openOperationsAt,
    openSourceCatalog,
    closeEvent,
    closeAssistant,
    askAboutEvent,
  };
}
