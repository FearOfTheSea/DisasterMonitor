import { act, renderHook, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { useAssistantConversation } from '@/features/assistant/hooks/useAssistantConversation';

function jsonResponse(value: unknown, status = 200) {
  return new Response(JSON.stringify(value), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

function persistedAssistantResponse() {
  return {
    message: 'Previous answer',
    conversation_id: 'conversation-1',
    model: 'source-backed-agent',
    response_type: 'current_disaster_earthquake',
    selected_event: {
      event_id: 'event-1',
      disaster: 'earthquake',
      location: 'Colombia',
      event_time: '2026-08-21T09:00:00Z',
      geometry: null,
      measurements: [],
      provider_ids: ['provider-event-1'],
      geography_status: 'in_country',
      source: {
        source_id: 'event-source',
        publisher: 'Event publisher',
        title: 'Event title',
        canonical_url: 'https://example.test/event',
        retrieved_at: '2026-08-21T10:00:00Z',
      },
    },
    sources: [],
    warnings: ['Report warning'],
    sections: [],
    partial: false,
    media_gallery: {
      event_id: 'event-1',
      physical_event_id: 'physical-event-1',
      generated_at: '2026-08-21T10:00:00Z',
      rejected_count: 2,
      provider_ids: ['fixture-media'],
      warnings: ['Gallery warning'],
      items: [
        {
          media_id: `media:${'a'.repeat(64)}:png`,
          image_url: `http://localhost:8001/api/v1/media/media:${'a'.repeat(64)}:png`,
          event_id: 'event-1',
          physical_event_id: 'physical-event-1',
          source_id: 'photo-source',
          publisher: 'Photo publisher',
          source_page_url: 'https://example.test/photo',
          caption: 'Rescue crews after the earthquake.',
          credit: 'Agency',
          credit_kind: 'agency',
          published_at: '2026-08-21T09:30:00Z',
          captured_at: null,
          license_name: null,
          license_url: null,
          rights_status: 'source_preview',
          role: 'rescue_effort',
          association_status: 'corroborated',
          association_rule_ids: ['media.association.publication_window'],
          association_detail: 'The event metadata agrees.',
          uncertainty: 'Contextual source media.',
          content_sha256: 'a'.repeat(64),
          width: 640,
          height: 360,
        },
      ],
    },
  };
}

describe('useAssistantConversation', () => {
  afterEach(() => vi.restoreAllMocks());

  it('loads, continues, starts fresh, and deletes backend conversations', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch');
    fetchMock.mockResolvedValueOnce(
      jsonResponse([
        {
          conversation_id: 'conversation-1',
          created_at: '2026-08-21T10:00:00Z',
          updated_at: '2026-08-21T10:01:00Z',
          preview: 'Previous question',
        },
      ]),
    );
    fetchMock.mockResolvedValueOnce(
      jsonResponse({
        conversation_id: 'conversation-1',
        created_at: '2026-08-21T10:00:00Z',
        updated_at: '2026-08-21T10:01:00Z',
        messages: [
          {
            id: 'message-1',
            role: 'user',
            content: 'Previous question',
            created_at: '2026-08-21T10:00:00Z',
          },
          {
            id: 'message-2',
            role: 'assistant',
            content: 'Previous answer',
            created_at: '2026-08-21T10:01:00Z',
            assistant_response: persistedAssistantResponse(),
          },
        ],
      }),
    );
    fetchMock.mockResolvedValueOnce(
      jsonResponse({
        message: 'Follow-up answer',
        conversation_id: 'conversation-1',
        model: 'fake-model',
      }),
    );
    fetchMock.mockResolvedValueOnce(
      jsonResponse([
        {
          conversation_id: 'conversation-1',
          created_at: '2026-08-21T10:00:00Z',
          updated_at: '2026-08-21T10:02:00Z',
          preview: 'Previous question',
        },
      ]),
    );
    fetchMock.mockResolvedValueOnce(new Response(null, { status: 204 }));

    const { result } = renderHook(() => useAssistantConversation());
    await waitFor(() => expect(result.current.conversations).toHaveLength(1));

    await act(async () => {
      await result.current.selectConversation('conversation-1');
    });
    expect(result.current.messages.map((message) => message.content)).toEqual([
      'Previous question',
      'Previous answer',
    ]);
    expect(result.current.messages[1].report?.warnings).toEqual(['Report warning']);
    expect(result.current.messages[1].report?.mediaGallery).toMatchObject({
      rejected_count: 2,
      warnings: ['Gallery warning'],
      items: [{ source_id: 'photo-source' }],
    });

    await act(async () => {
      await result.current.submit('Follow-up');
    });
    expect(result.current.messages.at(-1)?.content).toBe('Follow-up answer');
    expect(fetchMock.mock.calls[2][1]?.body).toEqual(
      expect.stringContaining('"conversation_id":"conversation-1"'),
    );

    await act(async () => {
      await result.current.deleteConversation('conversation-1');
    });
    expect(result.current.conversationId).toBeNull();
    expect(result.current.messages).toHaveLength(1);
    expect(result.current.conversations).toEqual([]);
  });

  it('keeps the completed turn when the background conversation refresh fails', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch');
    fetchMock.mockResolvedValueOnce(jsonResponse([]));
    fetchMock.mockResolvedValueOnce(
      jsonResponse({
        message: 'Answer from the assistant.',
        conversation_id: 'conversation-1',
        model: 'fake-model',
      }),
    );
    fetchMock.mockResolvedValueOnce(
      new Response('upstream unavailable', { status: 503 }),
    );

    const { result } = renderHook(() => useAssistantConversation());
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));

    await act(async () => {
      await result.current.submit('What happened?');
    });

    expect(result.current.messages.at(-1)?.content).toBe('Answer from the assistant.');
    expect(result.current.conversations).toEqual([]);
    expect(result.current.status).toBe('idle');
    expect(result.current.error).toBeNull();
  });
});
