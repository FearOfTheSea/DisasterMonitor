import { describe, expect, it } from 'vitest';

import { SessionConversationStore } from '@/shared/storage/sessionConversationStore';
import { commonOperationalPicture, multimodalState } from './fixtures/multimodal';

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
      messages: [
        { id: 'm1', role: 'user' as const, content: 'Zoom into Japan.' },
        {
          id: 'm2',
          role: 'assistant' as const,
          content: 'Showing Japan on the map.',
          mapAction: {
            type: 'fit_bounds' as const,
            bounds: [122, 20, 154, 46] as [number, number, number, number],
            label: 'Japan',
            max_zoom: 10,
          },
        },
      ],
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

  it('rejects stored COP data that bypasses transport provenance validation', () => {
    const browserStorage = storage();
    const unsafe = structuredClone(commonOperationalPicture);
    unsafe.layers[0].features[0].authority = 'official_source' as never;
    browserStorage.setItem(
      'disaster-monitor.conversation.v1',
      JSON.stringify({
        conversationId: 'session-unsafe',
        messages: [
          {
            id: 'unsafe',
            role: 'assistant',
            content: 'unsafe',
            report: {
              responseType: 'current_disaster',
              sources: [],
              warnings: [],
              sections: [],
              partial: false,
              multimodal: multimodalState,
              commonOperationalPicture: unsafe,
            },
          },
        ],
      }),
    );

    expect(new SessionConversationStore(browserStorage).load()).toEqual({
      conversationId: null,
      messages: [],
    });
  });
});
