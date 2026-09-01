import { afterEach, describe, expect, it, vi } from 'vitest';

import {
  createRefreshController,
  REFRESH_POLICIES,
} from '@/shared/model/refreshPolicy';

function setVisibility(value: DocumentVisibilityState) {
  Object.defineProperty(document, 'visibilityState', {
    configurable: true,
    value,
  });
  document.dispatchEvent(new Event('visibilitychange'));
}

describe('dataset refresh policies', () => {
  afterEach(() => {
    vi.useRealTimers();
    setVisibility('visible');
  });

  it('keeps client polling distinct from source freshness claims', () => {
    const intervals = new Set(
      Object.values(REFRESH_POLICIES).map((policy) => policy.visibleIntervalMs),
    );

    expect(intervals.size).toBe(Object.keys(REFRESH_POLICIES).length);
    expect(REFRESH_POLICIES['active-incidents'].staleAfterMs).toBeNull();
    expect(REFRESH_POLICIES['incident-watches'].visibleIntervalMs).not.toBe(
      REFRESH_POLICIES['weather-alerts'].visibleIntervalMs,
    );
    expect(REFRESH_POLICIES['source-catalog'].freshnessSemantics).toMatch(
      /client polling/i,
    );
  });

  it('does not overlap requests and schedules the next run after completion', async () => {
    vi.useFakeTimers();
    let complete: (() => void) | undefined;
    const task = vi.fn(
      () =>
        new Promise<void>((resolve) => {
          complete = resolve;
        }),
    );
    const controller = createRefreshController(
      REFRESH_POLICIES['active-incidents'],
      task,
      document,
    );

    controller.start();
    expect(task).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(
      REFRESH_POLICIES['active-incidents'].visibleIntervalMs * 2,
    );
    expect(task).toHaveBeenCalledTimes(1);

    complete?.();
    await Promise.resolve();
    await vi.advanceTimersByTimeAsync(
      REFRESH_POLICIES['active-incidents'].visibleIntervalMs,
    );
    expect(task).toHaveBeenCalledTimes(2);
    controller.stop();
  });

  it('pauses while hidden and refreshes once when visibility returns', async () => {
    vi.useFakeTimers();
    const task = vi.fn().mockResolvedValue(undefined);
    const controller = createRefreshController(
      REFRESH_POLICIES['weather-alerts'],
      task,
      document,
    );

    controller.start();
    await Promise.resolve();
    setVisibility('hidden');
    await vi.advanceTimersByTimeAsync(
      REFRESH_POLICIES['weather-alerts'].visibleIntervalMs * 3,
    );
    expect(task).toHaveBeenCalledTimes(1);

    setVisibility('visible');
    await Promise.resolve();
    expect(task).toHaveBeenCalledTimes(2);
    controller.stop();
  });
});
