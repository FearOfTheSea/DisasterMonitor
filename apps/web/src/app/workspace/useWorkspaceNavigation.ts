'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import {
  DEFAULT_WORKSPACE_LOCATION,
  parseWorkspaceLocation,
  serializeWorkspaceLocation,
  type Destination,
  type ExplorePane,
  type WorkspaceLocation,
  type WorkspaceSection,
} from './workspaceLocation';

export function useWorkspaceNavigation() {
  const [location, setLocation] = useState<WorkspaceLocation>(
    DEFAULT_WORKSPACE_LOCATION,
  );
  const locationRef = useRef(location);

  useEffect(() => {
    const restore = () => {
      const restored = parseWorkspaceLocation(window.location.search);
      locationRef.current = restored;
      setLocation(restored);
    };
    restore();
    window.addEventListener('popstate', restore);
    return () => window.removeEventListener('popstate', restore);
  }, []);

  const update = useCallback(
    (change: Partial<WorkspaceLocation>, incidentId?: string | null) => {
      const next = { ...locationRef.current, ...change };
      locationRef.current = next;
      const parameters = new URLSearchParams(
        serializeWorkspaceLocation(window.location.search, next),
      );
      if (incidentId === null) parameters.delete('i');
      else if (incidentId !== undefined) parameters.set('i', incidentId);
      const query = parameters.toString();
      window.history.pushState(
        null,
        '',
        `${window.location.pathname}${query ? `?${query}` : ''}${window.location.hash}`,
      );
      setLocation(next);
    },
    [],
  );

  const navigate = useCallback(
    (destination: Destination, section?: WorkspaceSection) => {
      update({ destination, ...(section ? { section } : {}) });
    },
    [update],
  );
  const openPane = useCallback(
    (explorePane: ExplorePane, incidentId?: string | null) => {
      update({ destination: 'explore', explorePane }, incidentId);
    },
    [update],
  );
  const openSection = useCallback(
    (section: WorkspaceSection) => {
      const destination: Destination = ['watches', 'bookmarks', 'activity'].includes(
        section,
      )
        ? 'saved'
        : 'tools';
      update({ destination, section });
    },
    [update],
  );

  return { ...location, navigate, openPane, openSection };
}
