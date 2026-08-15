'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';

import {
  AssistantClient,
  toAssistantReport,
} from '@/features/assistant/api/assistantClient';
import { DEFAULT_MAP_VIEW, API_BASE_URL } from '@/shared/config/runtime';
import { SessionConversationStore } from '@/shared/storage/sessionConversationStore';
import type {
  ConversationMessage,
  ConversationState,
  ConversationStatus,
  MapView,
} from '@/shared/types/assistant';

const welcomeMessage: ConversationMessage = {
  id: 'welcome',
  role: 'assistant',
  content:
    'Ask about the map, disaster concepts, or supported source-backed investigations. Selected current events may include conservatively associated source photos; operator-supplied images remain a separate analytical path.',
};

export function useAssistantConversation() {
  const store = useMemo(() => new SessionConversationStore(), []);
  const client = useMemo(() => new AssistantClient(API_BASE_URL), []);
  const [state, setState] = useState<ConversationState>(() => {
    const loaded = store.load();
    return loaded.messages.length > 0
      ? loaded
      : { conversationId: null, messages: [welcomeMessage] };
  });
  const [status, setStatus] = useState<ConversationStatus>('idle');
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    store.save(state);
  }, [state, store]);

  const submit = useCallback(
    async (question: string, mapView: MapView = DEFAULT_MAP_VIEW) => {
      const normalizedQuestion = question.trim();
      if (!normalizedQuestion || status === 'loading') {
        return;
      }

      const userMessage: ConversationMessage = {
        id: crypto.randomUUID(),
        role: 'user',
        content: normalizedQuestion,
      };
      setState((current) => ({
        ...current,
        messages: [...current.messages, userMessage],
      }));
      setStatus('loading');
      setError(null);

      try {
        const response = await client.ask(
          normalizedQuestion,
          state.conversationId,
          mapView,
        );
        const report = toAssistantReport(response);
        setState((current) => ({
          conversationId: response.conversation_id,
          messages: [
            ...current.messages,
            {
              id: crypto.randomUUID(),
              role: 'assistant',
              content: response.message,
              ...(response.map_action ? { mapAction: response.map_action } : {}),
              ...(report ? { report } : {}),
            },
          ],
        }));
        setStatus('idle');
      } catch (caught) {
        setStatus('error');
        setError(caught instanceof Error ? caught.message : 'The assistant failed.');
      }
    },
    [client, state.conversationId, status],
  );

  const clear = useCallback(() => {
    store.clear();
    setState({ conversationId: null, messages: [welcomeMessage] });
    setStatus('idle');
    setError(null);
  }, [store]);

  return { ...state, status, error, submit, clear };
}
