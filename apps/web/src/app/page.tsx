'use client';

import { useRef } from 'react';

import { useAssistantConversation } from '@/features/assistant/hooks/useAssistantConversation';
import { AssistantPanel } from '@/features/assistant/ui/AssistantPanel';
import {
  CommandPalette,
  type CommandPaletteHandle,
} from '@/features/commands/ui/CommandPalette';
import { useActiveIncidents } from '@/features/incidents/hooks/useActiveIncidents';
import { ActiveIncidentsPanel } from '@/features/incidents/ui/ActiveIncidentsPanel';
import { SelectedEventPane } from '@/features/incidents/ui/SelectedEventPane';
import { disasterLabel } from '@/features/incidents/ui/incidentPresentation';
import { GroundImageryPanel } from '@/features/imagery/ui/GroundImageryPanel';
import { WorkspaceHelp } from '@/features/help/ui/WorkspaceHelp';
import { DisasterMap } from '@/features/map/ui/DisasterMap';
import { useWeatherAlerts } from '@/features/weather/hooks/useWeatherAlerts';
import { useMapWorkspace } from '@/app/workspace/useMapWorkspace';
import { SecondaryWorkspaces } from '@/app/workspace/SecondaryWorkspaces';
import { ToolsMenu } from '@/app/workspace/ToolsMenu';
import { useWorkspaceActions } from '@/app/workspace/useWorkspaceActions';
import { useWorkspaceNavigation } from '@/app/workspace/useWorkspaceNavigation';
import { useWorkspacePresentation } from '@/app/workspace/useWorkspacePresentation';
import { useWorkspaceScrollRestoration } from '@/app/workspace/useWorkspaceScrollRestoration';

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

export default function Home() {
  const conversation = useAssistantConversation();
  const activeIncidents = useActiveIncidents();
  const weatherAlerts = useWeatherAlerts();
  const navigation = useWorkspaceNavigation();
  const { navigate, openPane } = navigation;
  useWorkspaceScrollRestoration(navigation.destination, navigation.section);
  const commandPaletteRef = useRef<CommandPaletteHandle>(null);
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

  const presentation = useWorkspacePresentation({
    messages: conversation.messages,
    snapshot: activeIncidents.snapshot,
    mapLayerState,
    watchFocusIncident,
    selectedIncidentId: usableSelectedIncidentId,
  });
  const {
    areaOfInterest,
    commonOperationalPicture,
    selectedEvent,
    evidenceStateVersion,
    displayedIncidents,
    displayedCorrelations,
    displayedSnapshot,
    mapIncidents,
    selectedIncident,
  } = presentation;
  const actions = useWorkspaceActions({
    submit: conversation.submit,
    mapView,
    mapLayerState,
    setMapLayerState,
    incidents: activeIncidents.snapshot?.incidents,
    selectedIncidentId: usableSelectedIncidentId,
    selectedIncident,
    selectActiveIncident: handleSelectActiveIncident,
    selectWatchIncident: handleSelectWatchIncident,
    clearSelectedIncident,
    setFocusRequestToken,
    selectRegion: handleSelectRegion,
    navigate,
    openPane,
    openSection: navigation.openSection,
  });
  const {
    assistantDraft,
    setAssistantDraft,
    assistantFocusToken,
    commands,
    selectIncident,
    selectWatchIncident,
    submitQuestion,
    openOperationsAt,
    closeEvent,
    closeAssistant,
    askAboutEvent,
  } = actions;
  const explorePane = navigation.explorePane ?? (selectedIncident ? 'ground' : null);
  const eventPaneOpen = explorePane === 'event' && Boolean(selectedIncident);
  const assistantOpen = explorePane === 'assistant';
  const groundOpen = explorePane === 'ground' && Boolean(selectedIncident);
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
          <ToolsMenu onSelect={navigation.openSection} />
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
            onSubmit={submitQuestion}
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
            incidentLabel={`${disasterLabel(selectedIncident.disaster)} · ${selectedIncident.location}`}
            incidentTime={selectedIncident.event_time}
            onClose={() => openPane('event')}
          />
        </div>
      )}
      <SecondaryWorkspaces navigation={navigation} operationsProps={operationsProps} />
    </main>
  );
}
