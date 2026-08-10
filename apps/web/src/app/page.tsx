'use client';

import { useCallback, useState } from 'react';

import { AssistantPanel } from '@/features/assistant/ui/AssistantPanel';
import { useAssistantConversation } from '@/features/assistant/hooks/useAssistantConversation';
import { DisasterMap } from '@/features/map/ui/DisasterMap';
import { DEFAULT_MAP_VIEW } from '@/shared/config/runtime';
import type { MapView } from '@/shared/types/assistant';

export default function Home() {
  const [assistantOpen, setAssistantOpen] = useState(false);
  const [mapView, setMapView] = useState<MapView>(DEFAULT_MAP_VIEW);
  const conversation = useAssistantConversation();
  const handleViewChange = useCallback((view: MapView) => setMapView(view), []);
  const commonOperationalPicture = [...conversation.messages]
    .reverse()
    .find((message) => message.report?.commonOperationalPicture)
    ?.report?.commonOperationalPicture;

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
        <button
          className="assistant-toggle"
          type="button"
          aria-expanded={assistantOpen}
          onClick={() => setAssistantOpen((open) => !open)}
        >
          {assistantOpen ? 'Close assistant' : 'Open assistant'}
        </button>
      </header>
      <section className="workspace">
        <div className="map-region">
          <DisasterMap
            onViewChange={handleViewChange}
            commonOperationalPicture={commonOperationalPicture}
          />
          <div className="map-overlay">OpenStreetMap base layer · Hanoi view</div>
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
      </section>
    </main>
  );
}
