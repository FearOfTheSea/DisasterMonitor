'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';

import {
  AssistantClient,
  toAssistantReport,
} from '@/features/assistant/api/assistantClient';
import { DEFAULT_MAP_VIEW, API_BASE_URL } from '@/shared/config/runtime';
import type {
  AssistantResponse,
  ConversationMessage,
  ConversationSummary,
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
  const client = useMemo(() => new AssistantClient(API_BASE_URL), []);
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [messages, setMessages] = useState<ConversationMessage[]>([welcomeMessage]);
  const [conversations, setConversations] = useState<ConversationSummary[]>([]);
  const [status, setStatus] = useState<ConversationStatus>('idle');
  const [error, setError] = useState<string | null>(null);
  const [conversationLoading, setConversationLoading] = useState(false);

  useEffect(() => {
    let current = true;
    client
      .listConversations()
      .then((loaded) => {
        if (current) {
          setConversations(loaded);
        }
      })
      .catch((caught) => {
        if (current) {
          setError(
            caught instanceof Error
              ? caught.message
              : 'The conversations failed to load.',
          );
        }
      });
    return () => {
      current = false;
    };
  }, [client]);

  const startNewConversation = useCallback(() => {
    if (status === 'loading') {
      return;
    }
    setConversationId(null);
    setMessages([welcomeMessage]);
    setStatus('idle');
    setError(null);
  }, [status]);

  const selectConversation = useCallback(
    async (selectedId: string | null) => {
      if (status === 'loading') {
        return;
      }
      if (!selectedId) {
        startNewConversation();
        return;
      }
      setConversationLoading(true);
      setError(null);
      try {
        const loaded = await client.getConversation(selectedId);
        setConversationId(loaded.conversation_id);
        setMessages(
          loaded.messages.map(({ id, role, content, assistant_response }) => {
            const report = assistant_response
              ? toAssistantReport(assistant_response)
              : undefined;
            return {
              id,
              role,
              content,
              ...(assistant_response?.map_action
                ? { mapAction: assistant_response.map_action }
                : {}),
              ...(assistant_response?.operator_actions?.length
                ? { operatorActions: assistant_response.operator_actions }
                : {}),
              ...(report ? { report } : {}),
            };
          }),
        );
        setStatus('idle');
      } catch (caught) {
        setError(
          caught instanceof Error ? caught.message : 'The conversation failed to load.',
        );
      } finally {
        setConversationLoading(false);
      }
    },
    [client, startNewConversation, status],
  );

  const deleteConversation = useCallback(
    async (selectedId: string) => {
      if (status === 'loading') {
        return;
      }
      setError(null);
      try {
        await client.deleteConversation(selectedId);
        setConversations((current) =>
          current.filter((conversation) => conversation.conversation_id !== selectedId),
        );
        if (conversationId === selectedId) {
          startNewConversation();
        }
      } catch (caught) {
        setError(
          caught instanceof Error
            ? caught.message
            : 'The conversation failed to delete.',
        );
      }
    },
    [client, conversationId, startNewConversation, status],
  );

  const submit = useCallback(
    async (
      question: string,
      mapView: MapView = DEFAULT_MAP_VIEW,
    ): Promise<AssistantResponse | undefined> => {
      const normalizedQuestion = question.trim();
      if (!normalizedQuestion || status === 'loading') {
        return undefined;
      }

      const userMessage: ConversationMessage = {
        id: crypto.randomUUID(),
        role: 'user',
        content: normalizedQuestion,
      };
      setMessages((current) => [...current, userMessage]);
      setStatus('loading');
      setError(null);

      try {
        const response = await client.ask(normalizedQuestion, conversationId, mapView);
        const report = toAssistantReport(response);
        setConversationId(response.conversation_id);
        setMessages((current) => [
          ...current,
          {
            id: crypto.randomUUID(),
            role: 'assistant',
            content: response.message,
            ...(response.map_action ? { mapAction: response.map_action } : {}),
            ...(response.operator_actions?.length
              ? { operatorActions: response.operator_actions }
              : {}),
            ...(report ? { report } : {}),
          },
        ]);
        const refreshedConversations = await tryLoadConversations(client);
        if (refreshedConversations) {
          setConversations(refreshedConversations);
        }
        setStatus('idle');
        return response;
      } catch (caught) {
        setStatus('error');
        setError(caught instanceof Error ? caught.message : 'The assistant failed.');
        return undefined;
      }
    },
    [client, conversationId, status],
  );

  const clear = startNewConversation;

  return {
    conversationId,
    messages,
    conversations,
    status,
    error,
    conversationLoading,
    submit,
    clear,
    startNewConversation,
    selectConversation,
    deleteConversation,
  };
}

async function tryLoadConversations(
  client: AssistantClient,
): Promise<ConversationSummary[] | undefined> {
  try {
    return await client.listConversations();
  } catch {
    return undefined;
  }
}
