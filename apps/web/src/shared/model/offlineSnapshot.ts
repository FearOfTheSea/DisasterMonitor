const MAXIMUM_OFFLINE_SNAPSHOT_BYTES = 2_000_000;

type StoredSnapshot<T> = {
  schemaVersion: 1;
  cachedAt: string;
  value: T;
};

export type OfflineSnapshot<T> = {
  cachedAt: string;
  value: T;
};

export function readOfflineSnapshot<T>(
  key: string,
  validate: (value: unknown) => value is T,
): OfflineSnapshot<T> | undefined {
  try {
    const raw = window.localStorage.getItem(key);
    if (!raw || raw.length > MAXIMUM_OFFLINE_SNAPSHOT_BYTES) return undefined;
    const parsed = JSON.parse(raw) as Partial<StoredSnapshot<unknown>>;
    if (
      parsed.schemaVersion !== 1 ||
      typeof parsed.cachedAt !== 'string' ||
      !validate(parsed.value)
    ) {
      return undefined;
    }
    return { cachedAt: parsed.cachedAt, value: parsed.value };
  } catch {
    return undefined;
  }
}

export function writeOfflineSnapshot<T>(key: string, value: T): string | undefined {
  try {
    const cachedAt = new Date().toISOString();
    const serialized = JSON.stringify({ schemaVersion: 1, cachedAt, value });
    if (serialized.length > MAXIMUM_OFFLINE_SNAPSHOT_BYTES) return undefined;
    window.localStorage.setItem(key, serialized);
    return cachedAt;
  } catch {
    return undefined;
  }
}
