import { act, renderHook, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { useAssistantConversation } from '@/features/assistant/hooks/useAssistantConversation';

function jsonResponse(value: unknown, status = 200) {
  return new Response(JSON.stringify(value), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
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
});
