export type RefreshDataset =
  | 'active-incidents'
  | 'incident-watches'
  | 'weather-alerts'
  | 'source-catalog'
  | 'satellite-availability';

export type RefreshPolicy = {
  dataset: RefreshDataset;
  visibleIntervalMs: number;
  hiddenIntervalMs: null;
  staleAfterMs: null;
  freshnessSemantics: string;
};

export const REFRESH_POLICIES: Record<RefreshDataset, RefreshPolicy> = {
  'active-incidents': {
    dataset: 'active-incidents',
    visibleIntervalMs: 5 * 60_000,
    hiddenIntervalMs: null,
    staleAfterMs: null,
    freshnessSemantics:
      'Five minutes is the client polling interval. Provider publication and observation times remain source-specific; no common stale threshold is claimed.',
  },
  'incident-watches': {
    dataset: 'incident-watches',
    visibleIntervalMs: 60_000,
    hiddenIntervalMs: null,
    staleAfterMs: null,
    freshnessSemantics:
      'One minute is the client polling interval for retained watch state. It does not change any user-configured Incident Watch scheduler interval.',
  },
  'weather-alerts': {
    dataset: 'weather-alerts',
    visibleIntervalMs: 2 * 60_000,
    hiddenIntervalMs: null,
    staleAfterMs: null,
    freshnessSemantics:
      'Two minutes is the client polling interval. Alert sent, effective, onset, expiry, and retrieval times retain their distinct source meanings.',
  },
  'source-catalog': {
    dataset: 'source-catalog',
    visibleIntervalMs: 60 * 60_000,
    hiddenIntervalMs: null,
    staleAfterMs: null,
    freshnessSemantics:
      'One hour is the client polling interval for maintained metadata and local configuration state, not a provider publication claim.',
  },
  'satellite-availability': {
    dataset: 'satellite-availability',
    visibleIntervalMs: 15 * 60_000,
    hiddenIntervalMs: null,
    staleAfterMs: null,
    freshnessSemantics:
      'Fifteen minutes is the client polling interval for configuration availability. It does not assert that a requested satellite observation exists.',
  },
};

type RefreshTask = (signal: AbortSignal) => Promise<void>;

export type RefreshController = {
  start: () => void;
  refreshNow: () => Promise<void>;
  stop: () => void;
};

export function createRefreshController(
  policy: RefreshPolicy,
  task: RefreshTask,
  ownerDocument: Document,
): RefreshController {
  let started = false;
  let timer: ReturnType<typeof setTimeout> | undefined;
  let active: Promise<void> | undefined;
  let request: AbortController | undefined;

  function clearTimer() {
    if (timer !== undefined) clearTimeout(timer);
    timer = undefined;
  }

  function schedule() {
    clearTimer();
    if (!started || ownerDocument.visibilityState === 'hidden') return;
    timer = setTimeout(() => {
      void run().catch(() => undefined);
    }, policy.visibleIntervalMs);
  }

  function run(): Promise<void> {
    if (active) return active;
    clearTimer();
    request = new AbortController();
    const currentRequest = request;
    active = Promise.resolve(task(currentRequest.signal)).finally(() => {
      if (request === currentRequest) request = undefined;
      active = undefined;
      schedule();
    });
    return active;
  }

  function onVisibilityChange() {
    if (ownerDocument.visibilityState === 'hidden') {
      clearTimer();
      return;
    }
    void run().catch(() => undefined);
  }

  return {
    start() {
      if (started) return;
      started = true;
      ownerDocument.addEventListener('visibilitychange', onVisibilityChange);
      if (ownerDocument.visibilityState === 'hidden') return;
      void run().catch(() => undefined);
    },
    refreshNow: run,
    stop() {
      if (!started) return;
      started = false;
      clearTimer();
      ownerDocument.removeEventListener('visibilitychange', onVisibilityChange);
      request?.abort();
      request = undefined;
    },
  };
}
