'use client';

import { useState } from 'react';

import {
  createIncidentWatch,
  fetchIncidentWatches,
} from '@/features/operations/api/incidentWatches';
import type { IncidentWatch } from '@/features/operations/model/incidentWatch';
import type { CreateIncidentWatchOperatorActionResponse } from '@/shared/api/generated/assistant';

type OperatorActionCardProps = {
  action: CreateIncidentWatchOperatorActionResponse;
  onWatchReady?: () => void;
};

export function OperatorActionCard({ action, onWatchReady }: OperatorActionCardProps) {
  const [saving, setSaving] = useState(false);
  const [created, setCreated] = useState(false);
  const [error, setError] = useState<string>();
  const country = action.scope.country_name ?? action.scope.country_code;
  const scopeLabel = action.scope.kind === 'worldwide' ? 'Worldwide' : country;

  async function confirm() {
    if (saving || created) return;
    if (action.scope.kind === 'country' && !country) {
      setError('The confirmed country scope is incomplete.');
      return;
    }
    setSaving(true);
    setError(undefined);
    try {
      const existingWatches = await fetchIncidentWatches();
      if (existingWatches.some((watch) => isExactWatch(watch, action))) {
        setCreated(true);
        onWatchReady?.();
        return;
      }
      await createIncidentWatch({
        disaster: action.disaster,
        scope:
          action.scope.kind === 'worldwide'
            ? { kind: 'worldwide' }
            : { kind: 'country', country: country as string },
        refresh_interval_seconds: action.refresh_interval_seconds,
      });
      setCreated(true);
      onWatchReady?.();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Watch creation failed.');
    } finally {
      setSaving(false);
    }
  }

  return (
    <article className="operator-action-card" aria-label="Incident Watch confirmation">
      <h3>{action.label}</h3>
      <p>
        Disaster: <strong>{action.disaster}</strong>
      </p>
      <p>
        Scope: <strong>{scopeLabel ?? 'Unavailable'}</strong>
        {action.scope.kind === 'country' && action.scope.country_code
          ? ` (${action.scope.country_code})`
          : ''}
      </p>
      <p>
        Refresh interval:{' '}
        <strong>{formatRefreshInterval(action.refresh_interval_seconds)}</strong>
      </p>
      <p>This creates persistent bounded monitoring.</p>
      <button type="button" onClick={() => void confirm()} disabled={saving || created}>
        {saving
          ? 'Creating Incident Watch…'
          : created
            ? 'Incident Watch created'
            : 'Confirm and create Incident Watch'}
      </button>
      {error && <p role="alert">{error}</p>}
    </article>
  );
}

function isExactWatch(
  watch: IncidentWatch,
  action: CreateIncidentWatchOperatorActionResponse,
): boolean {
  if (
    watch.disaster !== action.disaster ||
    watch.refresh_interval_seconds !== action.refresh_interval_seconds ||
    watch.scope.kind !== action.scope.kind
  ) {
    return false;
  }
  if (action.scope.kind === 'worldwide') return true;
  return (
    (watch.scope.country_code?.toUpperCase() ?? null) ===
      (action.scope.country_code?.toUpperCase() ?? null) ||
    (watch.scope.country_name?.toLowerCase() ?? null) ===
      (action.scope.country_name?.toLowerCase() ?? null)
  );
}

function formatRefreshInterval(seconds: number): string {
  const labels: Record<number, string> = {
    900: '900 seconds (15 minutes)',
    1800: '1,800 seconds (30 minutes)',
    3600: '3,600 seconds (1 hour)',
    21600: '21,600 seconds (6 hours)',
    86400: '86,400 seconds (24 hours)',
  };
  return labels[seconds] ?? `${seconds} seconds`;
}
