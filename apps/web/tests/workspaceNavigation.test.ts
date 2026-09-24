import { describe, expect, it } from 'vitest';
import { act, renderHook } from '@testing-library/react';

import {
  parseWorkspaceLocation,
  serializeWorkspaceLocation,
} from '@/app/workspace/workspaceLocation';
import { useWorkspaceNavigation } from '@/app/workspace/useWorkspaceNavigation';

describe('desktop workspace location', () => {
  it('restores destinations, subsections, and the Explore pane independently', () => {
    expect(parseWorkspaceLocation('?w=tools&sub=field-reports&pane=event')).toEqual({
      destination: 'tools',
      section: 'field-reports',
      explorePane: 'event',
    });
    expect(parseWorkspaceLocation('?w=saved&sub=activity&pane=assistant')).toEqual({
      destination: 'saved',
      section: 'activity',
      explorePane: 'assistant',
    });
    expect(parseWorkspaceLocation('?w=unknown&sub=bad&pane=bad')).toEqual({
      destination: 'explore',
      section: 'watches',
      explorePane: null,
    });
  });

  it('keeps map and unrelated parameters when navigation changes', () => {
    const next = serializeWorkspaceLocation('?c=42,10&z=3&custom=1', {
      destination: 'sources',
      section: 'watches',
      explorePane: 'event',
    });
    expect(new URLSearchParams(next).get('c')).toBe('42,10');
    expect(new URLSearchParams(next).get('custom')).toBe('1');
    expect(parseWorkspaceLocation(next).explorePane).toBe('event');
  });

  it('restores destination and pane with Back while leaving map coordinates in the URL', () => {
    window.history.replaceState(null, '', '/?c=35,139&z=4');
    const { result, unmount } = renderHook(() => useWorkspaceNavigation());
    act(() => result.current.openPane('event'));
    const eventUrl = window.location.href;
    act(() => result.current.navigate('sources'));
    expect(result.current.destination).toBe('sources');
    expect(new URLSearchParams(window.location.search).get('c')).toBe('35,139');
    act(() => {
      window.history.replaceState(null, '', eventUrl);
      window.dispatchEvent(new PopStateEvent('popstate'));
    });
    expect(result.current.destination).toBe('explore');
    expect(result.current.explorePane).toBe('event');
    unmount();
    window.history.replaceState(null, '', '/');
  });

  it('records the selected incident in the event history entry before opening Ground', () => {
    window.history.replaceState(null, '', '/?c=35,139&z=4');
    const { result, unmount } = renderHook(() => useWorkspaceNavigation());
    act(() => result.current.openPane('event', 'usgs:example'));
    const eventUrl = window.location.href;
    expect(new URL(eventUrl).searchParams.get('i')).toBe('usgs:example');
    act(() => result.current.openPane('ground'));
    act(() => {
      window.history.replaceState(null, '', eventUrl);
      window.dispatchEvent(new PopStateEvent('popstate'));
    });
    expect(result.current.explorePane).toBe('event');
    expect(new URLSearchParams(window.location.search).get('i')).toBe('usgs:example');
    unmount();
    window.history.replaceState(null, '', '/');
  });
});
