'use client';

import { useCallback, useMemo, useState } from 'react';

import { AssistantPanel } from '@/features/assistant/ui/AssistantPanel';
import { useAssistantConversation } from '@/features/assistant/hooks/useAssistantConversation';
import { assistantMapAreaOfInterest } from '@/features/map/model/assistantMapFocus';
import { DisasterMap } from '@/features/map/ui/DisasterMap';
import { OperationsPanel } from '@/features/operations/ui/OperationsPanel';
import { DEFAULT_MAP_VIEW } from '@/shared/config/runtime';
import type { MapView } from '@/shared/types/assistant';

export default function Home() {
  const [assistantOpen, setAssistantOpen] = useState(false);
  const [operationsOpen, setOperationsOpen] = useState(false);
  const [mapView, setMapView] = useState<MapView>(DEFAULT_MAP_VIEW);
  const conversation = useAssistantConversation();
  const handleViewChange = useCallback((view: MapView) => setMapView(view), []);
  const areaOfInterest = useMemo(
    () => assistantMapAreaOfInterest(conversation.messages),
    [conversation.messages],
  );
  const commonOperationalPicture = [...conversation.messages]
    .reverse()
    .find((message) => message.report?.commonOperationalPicture)
    ?.report?.commonOperationalPicture;
  const evidenceStateVersion = [...conversation.messages]
    .reverse()
    .find((message) => message.report?.decisionSupport?.evidence_state_version)?.report
    ?.decisionSupport?.evidence_state_version;

  return (
    <main className="app-shell">
      <header className="app-header">
        <div className="brand">
          <div className="brand-mark" aria-hidden="true">
            DM
          </div>
          <div>
            <h1>Disaster Monitor</h1>
            <p>Local-first map workspace</p>
          </div>
        </div>
        <div className="header-actions">
          <button
            type="button"
            aria-expanded={operationsOpen}
            onClick={() => setOperationsOpen((open) => !open)}
          >
            {operationsOpen ? 'Close operations' : 'Evidence operations'}
          </button>
          <button
            className="assistant-toggle"
            type="button"
            aria-expanded={assistantOpen}
            onClick={() => setAssistantOpen((open) => !open)}
          >
            {assistantOpen ? 'Close assistant' : 'Open assistant'}
          </button>
        </div>
      </header>
      <section className="workspace">
        <div className="map-region">
          <DisasterMap
            onViewChange={handleViewChange}
            commonOperationalPicture={commonOperationalPicture}
            areaOfInterest={areaOfInterest}
          />
          <div className="map-overlay">
            OpenStreetMap base layer · {mapView.centerLatitude.toFixed(2)},{' '}
            {mapView.centerLongitude.toFixed(2)} · zoom {mapView.zoom.toFixed(1)}
          </div>
        </div>
        {assistantOpen && (
          <AssistantPanel
            messages={conversation.messages}
            status={conversation.status}
            error={conversation.error}
            onSubmit={(question) => conversation.submit(question, mapView)}
            onClear={conversation.clear}
          />
        )}
        {operationsOpen && (
          <OperationsPanel
            evidenceStateVersion={evidenceStateVersion}
            onClose={() => setOperationsOpen(false)}
          />
        )}
      </section>
    </main>
  );
}
