'use client';

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import { AssistantPanel } from '@/features/assistant/ui/AssistantPanel';
import { useAssistantConversation } from '@/features/assistant/hooks/useAssistantConversation';
import { useActiveIncidents } from '@/features/incidents/hooks/useActiveIncidents';
import { ActiveIncidentsPanel } from '@/features/incidents/ui/ActiveIncidentsPanel';
import type { ActiveIncident } from '@/features/incidents/model/activeIncidents';
import { assistantMapAreaOfInterest } from '@/features/map/model/assistantMapFocus';
import {
  buildCommandRegistry,
  type CommandRegistryContext,
} from '@/features/commands/model/commandRegistry';
import { CommandPalette } from '@/features/commands/ui/CommandPalette';
import {
  createDefaultMapLayerState,
  filterCorrelationsForDisplay,
  filterIncidentsForDisplay,
  setMapLayerVisibility,
} from '@/features/map/model/mapLayerState';
import { DisasterMap } from '@/features/map/ui/DisasterMap';
import type { SatelliteMapState } from '@/features/map/ui/DisasterMap';
import {
  createMapUrlStateHistory,
  type MapUrlState,
  type MapUrlStateHistory,
} from '@/features/map/model/mapUrlState';
import {
  applyRegionalPreset,
  regionalPresetAfterViewChange,
  type RegionalPresetId,
  type RegionalSelection,
} from '@/features/map/model/regionalPresets';
import {
  observationTimeForSource,
  SATELLITE_IMAGERY_SOURCES,
} from '@/features/map/model/satelliteImagery';
import { OperationsPanel } from '@/features/operations/ui/OperationsPanel';
import { SourceCatalog } from '@/features/sources/ui/SourceCatalog';
import { useWeatherAlerts } from '@/features/weather/hooks/useWeatherAlerts';
import { DEFAULT_MAP_VIEW } from '@/shared/config/runtime';
import type { MapView } from '@/shared/types/assistant';

type IconProps = { className?: string };

function EvidenceIcon({ className }: IconProps) {
  return (
    <svg
      className={className}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <ellipse cx="12" cy="5" rx="7.5" ry="3" />
      <path d="M4.5 5v7c0 1.7 3.4 3 7.5 3s7.5-1.3 7.5-3V5" />
      <path d="M4.5 12v7c0 1.7 3.4 3 7.5 3s7.5-1.3 7.5-3v-7" />
    </svg>
  );
}

function AssistantIcon({ className }: IconProps) {
  return (
    <svg
      className={className}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d="M20 14.5a4 4 0 0 1-4 4H9l-5 3v-7a4 4 0 0 1-1-2.7V7a4 4 0 0 1 4-4h9a4 4 0 0 1 4 4z" />
      <path d="M8 9.5h.01M12 9.5h.01M16 9.5h.01" />
    </svg>
  );
}

function PositionIcon({ className }: IconProps) {
  return (
    <svg
      className={className}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <circle cx="12" cy="12" r="7" />
      <circle cx="12" cy="12" r="2" />
      <path d="M12 2v3M12 19v3M2 12h3M19 12h3" />
    </svg>
  );
}

export default function Home() {
  const [assistantOpen, setAssistantOpen] = useState(false);
  const [operationsOpen, setOperationsOpen] = useState(false);
  const [sourceCatalogOpen, setSourceCatalogOpen] = useState(false);
  const [selectedIncidentId, setSelectedIncidentId] = useState<string>();
  const [watchFocusIncident, setWatchFocusIncident] = useState<ActiveIncident>();
  const [mapLayerState, setMapLayerState] = useState(createDefaultMapLayerState);
  const [mapView, setMapView] = useState<MapView>(DEFAULT_MAP_VIEW);
  const [regionalSelection, setRegionalSelection] =
    useState<RegionalSelection>('custom');
  const [satelliteState, setSatelliteState] = useState<SatelliteMapState>(() => {
    const source = SATELLITE_IMAGERY_SOURCES[0];
    return {
      sourceId: source.id,
      observationTime: observationTimeForSource(source),
    };
  });
  const [focusRequestToken, setFocusRequestToken] = useState(0);
  const mapUrlHistory = useRef<MapUrlStateHistory | undefined>(undefined);
  const skipNextUrlWrite = useRef(false);
  const [defaultUrlState] = useState<MapUrlState>(() => {
    return {
      view: DEFAULT_MAP_VIEW,
      regionalPreset: 'custom',
      selectedIncidentId: undefined,
      layerState: createDefaultMapLayerState(),
      satelliteSourceId: satelliteState.sourceId,
      satelliteObservationTime: satelliteState.observationTime,
    };
  });
  const conversation = useAssistantConversation();
  const activeIncidents = useActiveIncidents();
  const weatherAlerts = useWeatherAlerts();
  const usableSelectedIncidentId =
    activeIncidents.status === 'success' &&
    selectedIncidentId &&
    !watchFocusIncident &&
    !activeIncidents.snapshot?.incidents.some(
      (incident) => incident.event_id === selectedIncidentId,
    )
      ? undefined
      : selectedIncidentId;
  const handleViewChange = useCallback((view: MapView) => {
    setMapView(view);
    setRegionalSelection((current) => regionalPresetAfterViewChange(current, view));
  }, []);
  const handleSelectRegion = useCallback((region: RegionalPresetId) => {
    const next = applyRegionalPreset(region);
    setRegionalSelection(next.regionalPreset);
    setMapView(next.view);
  }, []);
  const handleSelectActiveIncident = useCallback((incidentId: string) => {
    setWatchFocusIncident(undefined);
    setSelectedIncidentId(incidentId);
    setFocusRequestToken((current) => current + 1);
    setMapLayerState((current) =>
      setMapLayerVisibility(current, 'active-incidents', true),
    );
  }, []);
  const handleSelectWatchIncident = useCallback((incident: ActiveIncident) => {
    setWatchFocusIncident(incident);
    setSelectedIncidentId(incident.event_id);
    setFocusRequestToken((current) => current + 1);
    setMapLayerState((current) =>
      setMapLayerVisibility(current, 'active-incidents', true),
    );
  }, []);
  const handleToggleAssistant = useCallback(() => {
    setAssistantOpen((open) => {
      const nextOpen = !open;
      if (nextOpen) {
        setOperationsOpen(false);
        setSourceCatalogOpen(false);
      }
      return nextOpen;
    });
  }, []);
  const handleToggleOperations = useCallback(() => {
    setOperationsOpen((open) => {
      const nextOpen = !open;
      if (nextOpen) {
        setAssistantOpen(false);
        setSourceCatalogOpen(false);
      }
      return nextOpen;
    });
  }, []);
  const handleToggleSourceCatalog = useCallback(() => {
    setSourceCatalogOpen((open) => {
      const nextOpen = !open;
      if (nextOpen) {
        setAssistantOpen(false);
        setOperationsOpen(false);
      }
      return nextOpen;
    });
  }, []);

  useEffect(() => {
    const history = createMapUrlStateHistory(
      defaultUrlState,
      (restored) => {
        skipNextUrlWrite.current = true;
        setMapView(restored.view);
        setRegionalSelection(restored.regionalPreset);
        setSelectedIncidentId(restored.selectedIncidentId);
        setWatchFocusIncident(undefined);
        setMapLayerState(restored.layerState);
        setSatelliteState({
          sourceId: restored.satelliteSourceId,
          observationTime: restored.satelliteObservationTime,
        });
      },
      window,
    );
    mapUrlHistory.current = history;
    history.start();
    return () => {
      history.stop();
      mapUrlHistory.current = undefined;
    };
  }, [defaultUrlState]);

  useEffect(() => {
    if (skipNextUrlWrite.current) {
      skipNextUrlWrite.current = false;
      return;
    }
    mapUrlHistory.current?.schedule({
      view: mapView,
      regionalPreset: regionalSelection,
      selectedIncidentId: usableSelectedIncidentId,
      layerState: mapLayerState,
      satelliteSourceId: satelliteState.sourceId,
      satelliteObservationTime: satelliteState.observationTime,
    });
  }, [
    mapLayerState,
    mapView,
    regionalSelection,
    satelliteState,
    usableSelectedIncidentId,
  ]);
  const areaOfInterest = useMemo(
    () => assistantMapAreaOfInterest(conversation.messages),
    [conversation.messages],
  );
  const commonOperationalPicture = [...conversation.messages]
    .reverse()
    .find((message) => message.report?.commonOperationalPicture)
    ?.report?.commonOperationalPicture;
  const selectedEvent = [...conversation.messages]
    .reverse()
    .find((message) => message.report)?.report?.selectedEvent;
  const evidenceStateVersion = [...conversation.messages]
    .reverse()
    .find((message) => message.report?.decisionSupport?.evidence_state_version)?.report
    ?.decisionSupport?.evidence_state_version;
  const displayedIncidents = useMemo(() => {
    const snapshot = activeIncidents.snapshot;
    return snapshot
      ? filterIncidentsForDisplay(
          snapshot.incidents,
          snapshot.retrieved_at,
          mapLayerState.timeWindow,
        )
      : [];
  }, [activeIncidents.snapshot, mapLayerState.timeWindow]);
  const timeFilteredCorrelations = useMemo(() => {
    const snapshot = activeIncidents.snapshot;
    return snapshot
      ? filterCorrelationsForDisplay(
          snapshot.correlations ?? [],
          snapshot.incidents,
          snapshot.retrieved_at,
          mapLayerState.timeWindow,
        )
      : [];
  }, [activeIncidents.snapshot, mapLayerState.timeWindow]);
  const displayedCorrelations = useMemo(
    () =>
      mapLayerState.visibility['compound-correlations'] ? timeFilteredCorrelations : [],
    [mapLayerState.visibility, timeFilteredCorrelations],
  );
  const displayedSnapshot = useMemo(() => {
    const snapshot = activeIncidents.snapshot;
    return snapshot
      ? {
          ...snapshot,
          incidents: displayedIncidents,
          correlations: displayedCorrelations,
        }
      : undefined;
  }, [activeIncidents.snapshot, displayedCorrelations, displayedIncidents]);
  const mapIncidents = useMemo(() => {
    if (!watchFocusIncident) return displayedIncidents;
    return [
      watchFocusIncident,
      ...displayedIncidents.filter(
        (incident) => incident.event_id !== watchFocusIncident.event_id,
      ),
    ];
  }, [displayedIncidents, watchFocusIncident]);
  const openOperationsAt = useCallback((headingId?: string) => {
    setOperationsOpen(true);
    setAssistantOpen(false);
    setSourceCatalogOpen(false);
    if (headingId) {
      window.setTimeout(() => document.getElementById(headingId)?.focus(), 0);
    }
  }, []);
  const commands = useMemo(
    () =>
      buildCommandRegistry({
        incidents: activeIncidents.snapshot?.incidents ?? [],
        layerState: mapLayerState,
        selectedIncidentId: usableSelectedIncidentId,
        onSelectIncident: handleSelectActiveIncident,
        onFocusSelectedIncident: () => setFocusRequestToken((current) => current + 1),
        onSelectRegion: handleSelectRegion,
        onLayerStateChange: setMapLayerState,
        onOpenFindings: () => openOperationsAt('findings-center-heading'),
        onOpenSourceCatalog: () => {
          setSourceCatalogOpen(true);
          setAssistantOpen(false);
          setOperationsOpen(false);
        },
        onOpenIncidentWatches: () => openOperationsAt('incident-watches-heading'),
        onOpenOperations: () => openOperationsAt(),
      } satisfies CommandRegistryContext),
    [
      activeIncidents.snapshot?.incidents,
      handleSelectActiveIncident,
      handleSelectRegion,
      mapLayerState,
      openOperationsAt,
      usableSelectedIncidentId,
    ],
  );

  return (
    <main className="app-shell">
      <header className="app-header">
        <div className="brand">
          <div className="brand-mark" aria-hidden="true">
            DM
          </div>
          <div className="brand-copy">
            <h1>Disaster Monitor</h1>
            <p>Local-first map workspace</p>
          </div>
        </div>
        <div className="header-actions">
          <CommandPalette commands={commands} />
          <button
            type="button"
            aria-expanded={sourceCatalogOpen}
            aria-controls="source-catalog-panel"
            onClick={handleToggleSourceCatalog}
          >
            Source Catalog
          </button>
          <button
            type="button"
            aria-expanded={operationsOpen}
            aria-controls="operations-panel"
            onClick={handleToggleOperations}
          >
            <EvidenceIcon className="button-icon" />
            {operationsOpen ? 'Close operations' : 'Evidence operations'}
          </button>
          <button
            className="assistant-toggle"
            type="button"
            aria-expanded={assistantOpen}
            aria-controls="assistant-panel"
            onClick={handleToggleAssistant}
          >
            <AssistantIcon className="button-icon" />
            {assistantOpen ? 'Close assistant' : 'Open assistant'}
          </button>
        </div>
      </header>
      <section
        className={`workspace${assistantOpen ? ' workspace-assistant-open' : ''}${operationsOpen ? ' workspace-operations-open' : ''}${sourceCatalogOpen ? ' workspace-source-catalog-open' : ''}`}
      >
        <ActiveIncidentsPanel
          snapshot={displayedSnapshot}
          coverageSnapshot={activeIncidents.snapshot}
          status={activeIncidents.status}
          error={activeIncidents.error}
          selectedIncidentId={usableSelectedIncidentId}
          displayTimeWindow={mapLayerState.timeWindow}
          onSelectIncident={handleSelectActiveIncident}
          onRefresh={activeIncidents.refresh}
        />
        <div className="map-region">
          <DisasterMap
            onViewChange={handleViewChange}
            onSelectIncident={handleSelectActiveIncident}
            commonOperationalPicture={commonOperationalPicture}
            areaOfInterest={areaOfInterest}
            activeIncidents={mapIncidents}
            selectedIncidentId={usableSelectedIncidentId}
            selectedEvent={selectedEvent}
            layerState={mapLayerState}
            onLayerStateChange={setMapLayerState}
            correlationCount={displayedCorrelations.length}
            view={mapView}
            regionalSelection={regionalSelection}
            onRegionalSelectionChange={handleSelectRegion}
            satelliteState={satelliteState}
            onSatelliteStateChange={setSatelliteState}
            weatherAlerts={weatherAlerts.snapshot}
            focusRequestToken={focusRequestToken}
          />
          <div className="map-overlay" role="status" aria-live="polite">
            <PositionIcon className="map-overlay-icon" />
            <span>OpenStreetMap base layer</span>
            <span aria-hidden="true">·</span>
            <span>
              {mapView.centerLatitude.toFixed(2)}, {mapView.centerLongitude.toFixed(2)}
            </span>
            <span aria-hidden="true">·</span>
            <span>zoom {mapView.zoom.toFixed(1)}</span>
          </div>
        </div>
        {assistantOpen && (
          <AssistantPanel
            conversationId={conversation.conversationId}
            conversations={conversation.conversations}
            messages={conversation.messages}
            status={conversation.status}
            error={conversation.error}
            onSubmit={(question) => conversation.submit(question, mapView)}
            onClear={conversation.clear}
            onNewConversation={conversation.startNewConversation}
            onSelectConversation={conversation.selectConversation}
            onDeleteConversation={conversation.deleteConversation}
          />
        )}
        {operationsOpen && (
          <OperationsPanel
            evidenceStateVersion={evidenceStateVersion}
            activeIncidentsSnapshot={activeIncidents.snapshot}
            displayedIncidents={displayedIncidents}
            displayedCorrelations={displayedCorrelations}
            onSelectWatchIncident={handleSelectWatchIncident}
            onClose={() => setOperationsOpen(false)}
          />
        )}
        {sourceCatalogOpen && (
          <SourceCatalog onClose={() => setSourceCatalogOpen(false)} />
        )}
      </section>
    </main>
  );
}
