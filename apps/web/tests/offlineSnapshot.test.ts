import { beforeEach, describe, expect, it } from 'vitest';

import {
  readOfflineSnapshot,
  writeOfflineSnapshot,
} from '@/shared/model/offlineSnapshot';

const KEY = 'offline-snapshot:test';

function isRecord(value: unknown): value is { id: string } {
  return (
    typeof value === 'object' &&
    value !== null &&
    typeof (value as { id?: unknown }).id === 'string'
  );
}

describe('offlineSnapshot', () => {
  beforeEach(() => window.localStorage.clear());

  it('retains a validated read-only snapshot with its cache time', () => {
    const cachedAt = writeOfflineSnapshot(KEY, { id: 'finding-1' });

    expect(cachedAt).toBeDefined();
    expect(readOfflineSnapshot(KEY, isRecord)).toEqual({
      cachedAt,
      value: { id: 'finding-1' },
    });
  });

  it('fails closed for corrupt, incompatible, or oversized cache data', () => {
    window.localStorage.setItem(KEY, '{not-json');
    expect(readOfflineSnapshot(KEY, isRecord)).toBeUndefined();

    window.localStorage.setItem(
      KEY,
      JSON.stringify({ schemaVersion: 2, cachedAt: 'now', value: { id: 'x' } }),
    );
    expect(readOfflineSnapshot(KEY, isRecord)).toBeUndefined();
    expect(writeOfflineSnapshot(KEY, { id: 'x'.repeat(2_000_001) })).toBeUndefined();
  });
});
