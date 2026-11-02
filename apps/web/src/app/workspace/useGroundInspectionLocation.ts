'use client';

import { useEffect, useMemo, useState } from 'react';
import type { GroundImageryRetention } from '@/features/imagery/model/groundImageryRetention';

function validId(value: string | null, prefix: string): value is string {
  return Boolean(
    value && value.length <= 256 && value.startsWith(prefix) && /^[\w:-]+$/.test(value),
  );
}

export function readGroundInspection(search: string, incidentId: string) {
  const parameters = new URLSearchParams(search);
  const requestId = parameters.get('gr');
  if (parameters.get('i') !== incidentId || !validId(requestId, 'ground-imagery:'))
    return;
  const artifactId = parameters.get('ga');
  return {
    requestId,
    artifactId: validId(artifactId, 'artifact:') ? artifactId : undefined,
  };
}

export function clearGroundInspection(parameters: URLSearchParams) {
  parameters.delete('gr');
  parameters.delete('ga');
}

function replaceParameters(parameters: URLSearchParams) {
  const query = parameters.toString();
  window.history.replaceState(
    window.history.state,
    '',
    `${window.location.pathname}${query ? `?${query}` : ''}${window.location.hash}`,
  );
}

/** Replace the current inspection in place; only history traversal remounts the view. */
export function useGroundInspectionLocation() {
  const [navigationKey, setNavigationKey] = useState(0);
  useEffect(() => {
    const restore = () => setNavigationKey((key) => key + 1);
    window.addEventListener('popstate', restore);
    return () => window.removeEventListener('popstate', restore);
  }, []);
  const retention = useMemo<GroundImageryRetention>(
    () => ({
      read: (incidentId) => readGroundInspection(window.location.search, incidentId),
      saveRequest: (incidentId, requestId) => {
        const parameters = new URLSearchParams(window.location.search);
        if (parameters.get('i') !== incidentId) return;
        if (parameters.get('gr') !== requestId) parameters.delete('ga');
        parameters.set('gr', requestId);
        replaceParameters(parameters);
      },
      saveArtifact: (incidentId, requestId, artifactId) => {
        const parameters = new URLSearchParams(window.location.search);
        if (parameters.get('i') !== incidentId || parameters.get('gr') !== requestId)
          return;
        parameters.set('ga', artifactId);
        replaceParameters(parameters);
      },
      clear: (incidentId) => {
        const parameters = new URLSearchParams(window.location.search);
        if (parameters.get('i') !== incidentId) return;
        clearGroundInspection(parameters);
        replaceParameters(parameters);
      },
    }),
    [],
  );
  return { retention, navigationKey };
}
