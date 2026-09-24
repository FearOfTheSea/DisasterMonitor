'use client';

import { useEffect, useRef } from 'react';

import type { Destination, WorkspaceSection } from './workspaceLocation';

export function workspaceScrollKey(
  destination: Destination,
  section: WorkspaceSection,
): string {
  return destination === 'sources' ? 'sources' : `${destination}:${section}`;
}

export function useWorkspaceScrollRestoration(
  destination: Destination,
  section: WorkspaceSection,
) {
  const positions = useRef<Record<string, number>>({});
  const key = workspaceScrollKey(destination, section);

  useEffect(() => {
    if (destination === 'explore') return;
    const surface = document.querySelector<HTMLElement>(
      `[data-workspace-scroll-key="${key}"]`,
    );
    const scroll = surface?.querySelector<HTMLElement>(
      '.operations-scroll, .source-catalog-scroll',
    );
    if (!scroll) return;

    const storedPositions = positions.current;
    const saved = storedPositions[key] ?? 0;
    let restoring = saved > 0;
    const observer = new MutationObserver(() => {
      if (scroll.scrollHeight - scroll.clientHeight >= saved) {
        scroll.scrollTop = saved;
        restoring = false;
        observer.disconnect();
      }
    });
    if (saved > 0 && scroll.scrollHeight - scroll.clientHeight < saved) {
      observer.observe(scroll, { childList: true, subtree: true });
    } else {
      scroll.scrollTop = saved;
      restoring = false;
    }

    const remember = () => {
      if (restoring) return;
      storedPositions[key] = scroll.scrollTop;
      if (scroll.scrollTop > 0) observer.disconnect();
    };
    scroll.addEventListener('scroll', remember);
    return () => {
      scroll.removeEventListener('scroll', remember);
      observer.disconnect();
    };
  }, [destination, key]);
}
