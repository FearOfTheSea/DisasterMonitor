'use client';

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import { useAssistantConversation } from '@/features/assistant/hooks/useAssistantConversation';
import { executeAutomaticOperatorActions } from '@/features/assistant/model/operatorActions';
import { AssistantPanel } from '@/features/assistant/ui/AssistantPanel';
import {
  buildCommandRegistry,
  type CommandRegistryContext,
} from '@/features/commands/model/commandRegistry';
import {
  CommandPalette,
  type CommandPaletteHandle,
} from '@/features/commands/ui/CommandPalette';
import { useActiveIncidents } from '@/features/incidents/hooks/useActiveIncidents';
import { ActiveIncidentsPanel } from '@/features/incidents/ui/ActiveIncidentsPanel';
import { SelectedEventPane } from '@/features/incidents/ui/SelectedEventPane';
import { GroundImageryPanel } from '@/features/imagery/ui/GroundImageryPanel';
import { WorkspaceHelp } from '@/features/help/ui/WorkspaceHelp';
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
import { useWorkspaceNavigation } from '@/app/workspace/useWorkspaceNavigation';
import {
  useWorkspaceScrollRestoration,
  workspaceScrollKey,
} from '@/app/workspace/useWorkspaceScrollRestoration';
import type { WorkspaceSection } from '@/app/workspace/workspaceLocation';

type IconProps = { className?: string };

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

const SAVED_SECTIONS = ['watches', 'bookmarks', 'activity'] as const;
const TOOL_SECTIONS = [
  'field-reports',
  'workspace',
  'source-health',
  'evidence-history',
  'maintenance',
] as const;
function sectionLabel(section: WorkspaceSection): string {
  return section.replaceAll('-', ' ').replace(/^./, (letter) => letter.toUpperCase());
}

export default function Home() {
  const conversation = useAssistantConversation();
  const activeIncidents = useActiveIncidents();
  const weatherAlerts = useWeatherAlerts();
  const navigation = useWorkspaceNavigation();
  const { navigate, openPane, openSection } = navigation;
  useWorkspaceScrollRestoration(navigation.destination, navigation.section);
  const [assistantDraft, setAssistantDraft] = useState('');
  const [assistantFocusToken, setAssistantFocusToken] = useState(0);
  const commandPaletteRef = useRef<CommandPaletteHandle>(null);
  const [toolsOpen, setToolsOpen] = useState(false);
  const toolsRef = useRef<HTMLDivElement>(null);
  const toolsButtonRef = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    if (!toolsOpen) return;
    const dismiss = (event: MouseEvent | KeyboardEvent) => {
      if (event instanceof KeyboardEvent) {
        if (event.key === 'Escape') {
          setToolsOpen(false);
          toolsButtonRef.current?.focus();
        }
      } else if (
        event.target instanceof Node &&
        !toolsRef.current?.contains(event.target)
      )
        setToolsOpen(false);
    };
    document.addEventListener('mousedown', dismiss);
    document.addEventListener('keydown', dismiss);
    return () => {
      document.removeEventListener('mousedown', dismiss);
      document.removeEventListener('keydown', dismiss);
    };
  }, [toolsOpen]);
  const {
    mapView,
    basemap,
    setBasemap,
    mapLayerState,
    setMapLayerState,
    regionalSelection,
    satelliteState,
    setSatelliteState,
    focusRequestToken,
    setFocusRequestToken,
    watchFocusIncident,
    usableSelectedIncidentId,
    clearSelectedIncident,
    handleViewChange,
    handleSelectRegion,
    handleSelectActiveIncident,
    handleSelectWatchIncident,
  } = useMapWorkspace(activeIncidents);

  const openOperationsAt = useCallback(
    (headingId?: string) => {
      openSection(headingId === 'findings-center-heading' ? 'activity' : 'watches');
    },
    [openSection],
  );
  const openSourceCatalog = useCallback(() => navigate('sources'), [navigate]);
  const selectIncident = useCallback(
    (incidentId: string) => {
      handleSelectActiveIncident(incidentId);
      openPane('event', incidentId);
    },
    [handleSelectActiveIncident, openPane],
  );
  const selectWatchIncident = useCallback(
    (incident: Parameters<typeof handleSelectWatchIncident>[0]) => {
      handleSelectWatchIncident(incident);
      openPane('event', incident.event_id);
    },
    [handleSelectWatchIncident, openPane],
  );
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
  const displayedIncidents = useMemo(
    () =>
      activeIncidents.snapshot
        ? filterIncidentsForDisplay(
            activeIncidents.snapshot.incidents,
            activeIncidents.snapshot.retrieved_at,
            mapLayerState.timeWindow,
          )
        : [],
    [activeIncidents.snapshot, mapLayerState.timeWindow],
  );
  const timeFilteredCorrelations = useMemo(
    () =>
      activeIncidents.snapshot
        ? filterCorrelationsForDisplay(
            activeIncidents.snapshot.correlations ?? [],
            activeIncidents.snapshot.incidents,
            activeIncidents.snapshot.retrieved_at,
            mapLayerState.timeWindow,
          )
        : [],
    [activeIncidents.snapshot, mapLayerState.timeWindow],
  );
  const displayedCorrelations = useMemo(
    () =>
      mapLayerState.visibility['compound-correlations'] ? timeFilteredCorrelations : [],
    [mapLayerState.visibility, timeFilteredCorrelations],
  );
  const displayedSnapshot = useMemo(
    () =>
      activeIncidents.snapshot
        ? {
            ...activeIncidents.snapshot,
            incidents: displayedIncidents,
            correlations: displayedCorrelations,
          }
        : undefined,
    [activeIncidents.snapshot, displayedIncidents, displayedCorrelations],
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
    () =>
      mapIncidents.find((incident) => incident.event_id === usableSelectedIncidentId),
    [mapIncidents, usableSelectedIncidentId],
  );

  const handleAssistantSubmit = useCallback(
    async (question: string) => {
      const response = await conversation.submit(question, mapView);
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
      conversation,
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
        incidents: activeIncidents.snapshot?.incidents ?? [],
        layerState: mapLayerState,
        selectedIncidentId: usableSelectedIncidentId,
        onSelectIncident: selectIncident,
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
      mapLayerState,
      usableSelectedIncidentId,
      selectIncident,
      setFocusRequestToken,
      handleSelectRegion,
      setMapLayerState,
      openOperationsAt,
      openSourceCatalog,
    ],
  );

  const explorePane = navigation.explorePane ?? (selectedIncident ? 'event' : null);
  const eventPaneOpen = explorePane === 'event' && Boolean(selectedIncident);
  const assistantOpen = explorePane === 'assistant';
  const groundOpen = explorePane === 'ground' && Boolean(selectedIncident);
  const closeEvent = () => {
    clearSelectedIncident();
    openPane(null, null);
  };
  const closeAssistant = () => openPane(selectedIncident ? 'event' : null);
  const askAboutEvent = () => {
    if (selectedIncident) {
      setAssistantDraft(
        `What do we know about the ${selectedIncident.disaster.replaceAll('_', ' ')} in ${selectedIncident.country?.name ?? selectedIncident.location}?`,
      );
      setAssistantFocusToken((current) => current + 1);
    }
    openPane('assistant');
  };
  const selectTool = (section: WorkspaceSection) => {
    openSection(section);
    setToolsOpen(false);
  };
  const operationsProps = {
    evidenceStateVersion,
    selectedIncidentId: selectedIncident?.event_id,
    activeIncidentsSnapshot: activeIncidents.snapshot,
    displayedIncidents,
    displayedCorrelations,
    onSelectWatchIncident: selectWatchIncident,
    onClose: () => navigate('explore'),
  };

  return (
    <main className="app-shell">
      <header className="app-header">
        <div className="brand">
          <div className="brand-mark" aria-hidden="true">
            <svg viewBox="0 0 48 48" fill="none">
              <circle cx="24" cy="24" r="21" />
              <circle cx="24" cy="24" r="14" />
              <circle cx="24" cy="24" r="6" />
              <path d="m24 24 14-15" />
              <circle cx="38" cy="9" r="2" fill="currentColor" />
            </svg>
          </div>
          <div className="brand-copy">
            <h1>Disaster Monitor</h1>
          </div>
        </div>
        <nav className="desktop-nav" aria-label="Primary navigation">
          <button
            type="button"
            aria-current={navigation.destination === 'explore' ? 'page' : undefined}
            onClick={() => navigate('explore')}
          >
            Explore
          </button>
          <button
            type="button"
            aria-current={navigation.destination === 'saved' ? 'page' : undefined}
            onClick={() => navigate('saved', 'watches')}
          >
            Saved
          </button>
          <button
            type="button"
            aria-current={navigation.destination === 'sources' ? 'page' : undefined}
            onClick={() => navigate('sources')}
          >
            Sources
          </button>
          <div className="tools-menu-container" ref={toolsRef}>
            <button
              ref={toolsButtonRef}
              type="button"
              aria-expanded={toolsOpen}
              onClick={() => setToolsOpen((current) => !current)}
            >
              Tools
            </button>
            {toolsOpen && (
              <div className="tools-menu" role="menu">
                {TOOL_SECTIONS.map((section) => (
                  <button
                    key={section}
                    type="button"
                    role="menuitem"
                    onClick={() => selectTool(section)}
                  >
                    {sectionLabel(section)}
                  </button>
                ))}
              </div>
            )}
          </div>
        </nav>
        <div className="header-actions">
          <CommandPalette ref={commandPaletteRef} commands={commands} />
          <WorkspaceHelp onSearchCommands={() => commandPaletteRef.current?.open()} />
          <button
            className="assistant-toggle"
            type="button"
            aria-label="Ask a question"
            aria-expanded={assistantOpen}
            aria-controls="assistant-panel"
            onClick={() => openPane('assistant')}
          >
            <AssistantIcon className="button-icon" />
            Ask a question
          </button>
        </div>
      </header>
      <section
        className={`workspace observatory-explore${eventPaneOpen || assistantOpen ? ' observatory-reading-open' : ''}${eventPaneOpen ? ' observatory-event-open' : ''}${assistantOpen ? ' observatory-assistant-open' : ''}`}
        hidden={navigation.destination !== 'explore' || groundOpen}
      >
        <ActiveIncidentsPanel
          compact
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
          occurrenceStart={activeIncidents.occurrenceStart}
          occurrenceEnd={activeIncidents.occurrenceEnd}
          onOccurrenceStartChange={activeIncidents.setOccurrenceStart}
          onOccurrenceEndChange={activeIncidents.setOccurrenceEnd}
          onLoadMore={activeIncidents.loadMore}
          loadingMore={activeIncidents.loadingMore}
          onSelectIncident={selectIncident}
          onRefresh={activeIncidents.refresh}
        />
        <div
          className={`map-region${selectedIncident ? ' map-region-selection-active' : ''}`}
        >
          <div className="map-introduction">
            <PositionIcon className="map-introduction-icon" />
            <div>
              <h2>World overview</h2>
              <p>Select an event to see what&apos;s known</p>
            </div>
          </div>
          <DisasterMap
            onViewChange={handleViewChange}
            onSelectIncident={selectIncident}
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
            basemap={basemap}
            onBasemapChange={setBasemap}
          />
          <details className="map-overlay">
            <summary>
              <PositionIcon className="map-overlay-icon" />
              Map position
            </summary>
            <div role="status" aria-live="polite">
              <span>
                {basemap === 'atlas' ? 'Natural Earth atlas' : 'OpenStreetMap Streets'}
              </span>
              <span aria-hidden="true">·</span>
              <span>
                {mapView.centerLatitude.toFixed(2)},{' '}
                {mapView.centerLongitude.toFixed(2)}
              </span>
              <span aria-hidden="true">·</span>
              <span>zoom {mapView.zoom.toFixed(1)}</span>
            </div>
          </details>
        </div>
        {eventPaneOpen && selectedIncident && (
          <SelectedEventPane
            key={selectedIncident.event_id}
            incident={selectedIncident}
            snapshotRetrievedAt={
              activeIncidents.snapshot?.retrieved_at ??
              selectedIncident.source.retrieved_at
            }
            warnings={weatherAlerts.snapshot}
            onClose={closeEvent}
            onAsk={askAboutEvent}
            onGroundView={() => openPane('ground')}
          />
        )}
        {assistantOpen && (
          <AssistantPanel
            conversationId={conversation.conversationId}
            conversations={conversation.conversations}
            messages={conversation.messages}
            status={conversation.status}
            error={conversation.error}
            onSubmit={handleAssistantSubmit}
            draft={assistantDraft}
            onDraftChange={setAssistantDraft}
            selectedEventContext={
              selectedIncident?.country?.name ?? selectedIncident?.location
            }
            onReturnToEvent={selectedIncident ? () => openPane('event') : undefined}
            focusToken={assistantFocusToken}
            onClear={conversation.clear}
            onNewConversation={conversation.startNewConversation}
            onSelectConversation={conversation.selectConversation}
            onDeleteConversation={conversation.deleteConversation}
            onWatchReady={() => openOperationsAt('incident-watches-heading')}
            onClose={closeAssistant}
          />
        )}
      </section>
      {groundOpen && selectedIncident && (
        <div className="ground-workspace">
          <GroundImageryPanel
            incidentId={selectedIncident.event_id}
            incidentLabel={selectedIncident.country?.name ?? selectedIncident.location}
            onClose={() => openPane('event')}
          />
        </div>
      )}
      {navigation.destination === 'saved' && (
        <section
          className="secondary-workspace"
          aria-label="Saved workspace"
          data-workspace-scroll-key={workspaceScrollKey('saved', navigation.section)}
        >
          <div className="secondary-workspace-inner">
            <nav className="workspace-subnav" aria-label="Saved sections">
              {SAVED_SECTIONS.map((section) => (
                <button
                  key={section}
                  type="button"
                  aria-current={navigation.section === section ? 'page' : undefined}
                  onClick={() => navigate('saved', section)}
                >
                  {sectionLabel(section)}
                </button>
              ))}
            </nav>
            <OperationsPanel
              {...operationsProps}
              section={
                SAVED_SECTIONS.find((section) => section === navigation.section) ??
                'watches'
              }
            />
          </div>
        </section>
      )}
      {navigation.destination === 'sources' && (
        <section className="secondary-workspace" data-workspace-scroll-key="sources">
          <div className="secondary-workspace-inner">
            <SourceCatalog onClose={() => navigate('explore')} />
          </div>
        </section>
      )}
      {navigation.destination === 'tools' && (
        <section
          className="secondary-workspace"
          aria-label="Tools workspace"
          data-workspace-scroll-key={workspaceScrollKey('tools', navigation.section)}
        >
          <div className="secondary-workspace-inner">
            <nav className="workspace-subnav" aria-label="Tools sections">
              {TOOL_SECTIONS.map((section) => (
                <button
                  key={section}
                  type="button"
                  aria-current={navigation.section === section ? 'page' : undefined}
                  onClick={() => navigate('tools', section)}
                >
                  {sectionLabel(section)}
                </button>
              ))}
            </nav>
            <OperationsPanel
              {...operationsProps}
              section={
                TOOL_SECTIONS.find((section) => section === navigation.section) ??
                'field-reports'
              }
            />
          </div>
        </section>
      )}
    </main>
  );
}
