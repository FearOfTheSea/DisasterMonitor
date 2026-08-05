import { describe, expect, it } from 'vitest';

import { SessionConversationStore } from '@/shared/storage/sessionConversationStore';

function storage() {
  const values = new Map<string, string>();
  return {
    getItem: (key: string) => values.get(key) ?? null,
    setItem: (key: string, value: string) => values.set(key, value),
    removeItem: (key: string) => values.delete(key),
  };
}

describe('SessionConversationStore', () => {
  it('round-trips a browser-session conversation', () => {
    const browserStorage = storage();
    const store = new SessionConversationStore(browserStorage);
    const state = {
      conversationId: 'session-1',
      messages: [{ id: 'm1', role: 'user' as const, content: 'Hello' }],
    };

    store.save(state);

    expect(store.load()).toEqual(state);
  });

  it('ignores malformed stored data', () => {
    const browserStorage = storage();
    browserStorage.setItem('disaster-monitor.conversation.v1', '{bad json');

    expect(new SessionConversationStore(browserStorage).load()).toEqual({
      conversationId: null,
      messages: [],
    });
  });
});
