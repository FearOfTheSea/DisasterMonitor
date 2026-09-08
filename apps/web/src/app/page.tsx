'use client';

import { useCallback, useMemo } from 'react';

import { useAssistantConversation } from '@/features/assistant/hooks/useAssistantConversation';
import { executeAutomaticOperatorActions } from '@/features/assistant/model/operatorActions';
import { AssistantPanel } from '@/features/assistant/ui/AssistantPanel';
import {
  buildCommandRegistry,
  type CommandRegistryContext,
} from '@/features/commands/model/commandRegistry';
import { CommandPalette } from '@/features/commands/ui/CommandPalette';
import { useActiveIncidents } from '@/features/incidents/hooks/useActiveIncidents';
import { ActiveIncidentsPanel } from '@/features/incidents/ui/ActiveIncidentsPanel';
import { SelectedIncidentSummary } from '@/features/incidents/ui/SelectedIncidentSummary';
import { assistantMapAreaOfInterest } from '@/features/map/model/assistantMapFocus';
import {
  filterCorrelationsForDisplay,
  filterIncidentsForDisplay,
} from '@/features/map/model/mapLayerState';
import { DisasterMap } from '@/features/map/ui/DisasterMap';
import { OperationsPanel } from '@/features/operations/ui/OperationsPanel';
import { SourceCatalog } from '@/features/sources/ui/SourceCatalog';
import { useWeatherAlerts } from '@/features/weather/hooks/useWeatherAlerts';

import { useMapWorkspace } from '@/app/workspace/useMapWorkspace';
import { useWorkspacePanels } from '@/app/workspace/useWorkspacePanels';

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
  const conversation = useAssistantConversation();
  const submitAssistant = conversation.submit;
  const activeIncidents = useActiveIncidents();
  const weatherAlerts = useWeatherAlerts();
  const {
    mapView,
    mapLayerState,
    setMapLayerState,
    regionalSelection,
    satelliteState,
    setSatelliteState,
    focusRequestToken,
    setFocusRequestToken,
    watchFocusIncident,
    usableSelectedIncidentId,
    handleViewChange,
    handleSelectRegion,
    handleSelectActiveIncident,
    handleSelectWatchIncident,
  } = useMapWorkspace(activeIncidents);
  const { activePanel, togglePanel, closePanel, openOperationsAt, openSourceCatalog } =
    useWorkspacePanels();
  const assistantOpen = activePanel === 'assistant';
  const operationsOpen = activePanel === 'operations';
  const sourceCatalogOpen = activePanel === 'sources';
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
  const selectedIncident = useMemo(
    () =>
      mapIncidents.find((incident) => incident.event_id === usableSelectedIncidentId),
    [mapIncidents, usableSelectedIncidentId],
  );
  const handleAssistantSubmit = useCallback(
    async (question: string) => {
      const response = await submitAssistant(question, mapView);
      if (!response) return;
      const execution = executeAutomaticOperatorActions(
        response.operator_actions ?? [],
        mapLayerState,
      );
      setMapLayerState(execution.mapLayerState);
      for (const panel of execution.openPanels) {
        if (panel === 'sources') {
          openSourceCatalog();
        } else if (panel === 'findings') {
          openOperationsAt('findings-center-heading');
        } else if (panel === 'watches') {
          openOperationsAt('incident-watches-heading');
        } else {
          openOperationsAt();
        }
      }
    },
    [
      mapLayerState,
      mapView,
      openOperationsAt,
      openSourceCatalog,
      submitAssistant,
      setMapLayerState,
    ],
  );
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
        onOpenSourceCatalog: openSourceCatalog,
        onOpenIncidentWatches: () => openOperationsAt('incident-watches-heading'),
        onOpenOperations: () => openOperationsAt(),
      } satisfies CommandRegistryContext),
    [
      activeIncidents.snapshot?.incidents,
      handleSelectActiveIncident,
      handleSelectRegion,
      mapLayerState,
      openOperationsAt,
      openSourceCatalog,
      usableSelectedIncidentId,
      setFocusRequestToken,
      setMapLayerState,
    ],
  );

  return (
    <main className="app-shell">
      <header className="app-header">
        <div className="brand">
          <div className="brand-mark" aria-hidden="true">
            <svg viewBox="0 0 48 48" fill="none" aria-hidden="true">
              <circle cx="24" cy="24" r="21" />
              <circle cx="24" cy="24" r="14" />
              <circle cx="24" cy="24" r="6" />
              <path d="m24 24 14-15" />
              <circle cx="38" cy="9" r="2" fill="currentColor" />
            </svg>
          </div>
          <div className="brand-copy">
            <h1>Disaster Monitor</h1>
            <p>What&apos;s happening, clearly explained.</p>
          </div>
        </div>
        <div className="header-actions">
          <CommandPalette commands={commands} />
          <button
            type="button"
            aria-label="Source Catalog"
            aria-expanded={sourceCatalogOpen}
            aria-controls="source-catalog-panel"
            onClick={() => togglePanel('sources')}
          >
            <svg className="button-icon" viewBox="0 0 24 24" aria-hidden="true">
              <path d="m4 7 8-4 8 4-8 4-8-4Zm0 5 8 4 8-4M4 17l8 4 8-4" />
            </svg>
            Sources
          </button>
          <button
            type="button"
            aria-label={operationsOpen ? 'Close operations' : 'Evidence operations'}
            aria-expanded={operationsOpen}
            aria-controls="operations-panel"
            onClick={() => togglePanel('operations')}
          >
            <EvidenceIcon className="button-icon" />
            Saved
          </button>
          <button
            className="assistant-toggle"
            type="button"
            aria-label={assistantOpen ? 'Close assistant' : 'Open assistant'}
            aria-expanded={assistantOpen}
            aria-controls="assistant-panel"
            onClick={() => togglePanel('assistant')}
          >
            <AssistantIcon className="button-icon" />
            Ask
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
          search={activeIncidents.search}
          onSearchChange={activeIncidents.setSearch}
          view={activeIncidents.view}
          onViewChange={activeIncidents.setView}
          hazard={activeIncidents.hazard}
          onHazardChange={activeIncidents.setHazard}
          onLoadMore={activeIncidents.loadMore}
          loadingMore={activeIncidents.loadingMore}
          onSelectIncident={handleSelectActiveIncident}
          onRefresh={activeIncidents.refresh}
        />
        <div className="map-region">
          <div className="map-introduction">
            <PositionIcon className="map-introduction-icon" />
            <div>
              <h2>World overview</h2>
              <p>Select an event to see what&apos;s known</p>
            </div>
          </div>
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
          <details className="map-overlay">
            <summary>
              <PositionIcon className="map-overlay-icon" />
              Map position
            </summary>
            <div role="status" aria-live="polite">
              <span>OpenStreetMap base layer</span>
              <span aria-hidden="true">·</span>
              <span>
                {mapView.centerLatitude.toFixed(2)},{' '}
                {mapView.centerLongitude.toFixed(2)}
              </span>
              <span aria-hidden="true">·</span>
              <span>zoom {mapView.zoom.toFixed(1)}</span>
            </div>
          </details>
          <SelectedIncidentSummary
            incident={selectedIncident}
            onAsk={() => togglePanel('assistant')}
          />
        </div>
        {activePanel ? (
          <button
            className="panel-scrim"
            type="button"
            onClick={closePanel}
            aria-label="Close open panel"
          />
        ) : null}
        {assistantOpen && (
          <AssistantPanel
            conversationId={conversation.conversationId}
            conversations={conversation.conversations}
            messages={conversation.messages}
            status={conversation.status}
            error={conversation.error}
            onSubmit={handleAssistantSubmit}
            onClear={conversation.clear}
            onNewConversation={conversation.startNewConversation}
            onSelectConversation={conversation.selectConversation}
            onDeleteConversation={conversation.deleteConversation}
            onWatchReady={() => openOperationsAt('incident-watches-heading')}
            onClose={closePanel}
          />
        )}
        {operationsOpen && (
          <OperationsPanel
            evidenceStateVersion={evidenceStateVersion}
            activeIncidentsSnapshot={activeIncidents.snapshot}
            displayedIncidents={displayedIncidents}
            displayedCorrelations={displayedCorrelations}
            onSelectWatchIncident={handleSelectWatchIncident}
            onClose={closePanel}
          />
        )}
        {sourceCatalogOpen && <SourceCatalog onClose={closePanel} />}
      </section>
      <nav className="mobile-navigation" aria-label="Primary navigation">
        <button type="button" className="mobile-navigation-active" onClick={closePanel}>
          <PositionIcon className="button-icon" />
          Explore
        </button>
        <button
          type="button"
          onClick={() => togglePanel('assistant')}
          aria-pressed={assistantOpen}
        >
          <AssistantIcon className="button-icon" />
          Ask
        </button>
        <button
          type="button"
          onClick={() => togglePanel('operations')}
          aria-pressed={operationsOpen}
        >
          <EvidenceIcon className="button-icon" />
          Saved
        </button>
        <button
          type="button"
          onClick={() => togglePanel('sources')}
          aria-pressed={sourceCatalogOpen}
        >
          <svg className="button-icon" viewBox="0 0 24 24" aria-hidden="true">
            <path d="m4 7 8-4 8 4-8 4-8-4Zm0 5 8 4 8-4M4 17l8 4 8-4" />
          </svg>
          Sources
        </button>
      </nav>
    </main>
  );
}
