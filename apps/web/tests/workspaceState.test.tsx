import { act, renderHook } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { useWorkspacePanels } from '@/app/workspace/useWorkspacePanels';
import { useMapWorkspace } from '@/app/workspace/useMapWorkspace';

const incidents = { status: 'loading' as const, snapshot: undefined };

afterEach(() => {
  vi.useRealTimers();
  window.history.replaceState(null, '', '/');
});

describe('workspace coordination', () => {
  it('opens at most one panel and toggles the current panel closed', () => {
    const { result } = renderHook(() => useWorkspacePanels());
    expect(result.current.activePanel).toBe(null);
    act(() => result.current.togglePanel('assistant'));
    expect(result.current.activePanel).toBe('assistant');
    act(() => result.current.togglePanel('operations'));
    expect(result.current.activePanel).toBe('operations');
    act(() => result.current.togglePanel('operations'));
    expect(result.current.activePanel).toBe(null);
    act(() => result.current.openSourceCatalog());
    expect(result.current.activePanel).toBe('sources');
    act(() => result.current.closePanel());
    expect(result.current.activePanel).toBe(null);
  });

  it('restores URL view and preserves state through browser navigation', () => {
    vi.useFakeTimers();
    window.history.replaceState(null, '', '/?c=48,2&z=5&r=europe');
    const { result, unmount } = renderHook(() => useMapWorkspace(incidents));
    expect(result.current.mapView).toEqual({
      centerLatitude: 48,
      centerLongitude: 2,
      zoom: 5,
    });
    act(() => result.current.handleSelectActiveIncident('event-1'));
    expect(result.current.usableSelectedIncidentId).toBe('event-1');
    expect(result.current.mapLayerState.visibility['active-incidents']).toBe(true);
    act(() => vi.advanceTimersByTime(500));
    expect(new URLSearchParams(window.location.search).get('i')).toBe('event-1');
    act(() => {
      window.history.replaceState(null, '', '/?c=35,139&z=6');
      window.dispatchEvent(new PopStateEvent('popstate'));
    });
    expect(result.current.mapView).toEqual({
      centerLatitude: 35,
      centerLongitude: 139,
      zoom: 6,
    });
    expect(result.current.usableSelectedIncidentId).toBeUndefined();
    unmount();
    act(() => vi.runAllTimers());
    expect(new URLSearchParams(window.location.search).get('i')).toBe(null);
  });
});
