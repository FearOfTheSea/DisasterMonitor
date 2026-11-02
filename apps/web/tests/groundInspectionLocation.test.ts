import { act, cleanup, renderHook } from '@testing-library/react';
import { afterEach, expect, it } from 'vitest';
import {
  readGroundInspection,
  useGroundInspectionLocation,
} from '@/app/workspace/useGroundInspectionLocation';
import { useWorkspaceNavigation } from '@/app/workspace/useWorkspaceNavigation';
afterEach(() => {
  cleanup();
  window.history.replaceState(null, '', '/');
});
it('restores only well formed handles associated with the current event', () => {
  expect(
    readGroundInspection('?i=a&gr=ground-imagery:1&ga=artifact:before', 'a'),
  ).toEqual({ requestId: 'ground-imagery:1', artifactId: 'artifact:before' });
  expect(readGroundInspection('?i=a&gr=ground-imagery:1', 'b')).toBeUndefined();
  expect(readGroundInspection('?i=a&gr=https://elsewhere', 'a')).toBeUndefined();
});
it('retains request and capture without remounting or losing other URL state', () => {
  window.history.replaceState(
    { marker: 1 },
    '',
    '/?i=a&c=35,139&scan=retained&pane=ground#context',
  );
  const { result } = renderHook(() => useGroundInspectionLocation());
  const key = result.current.navigationKey;
  const port = result.current.retention;
  act(() => {
    port.saveRequest('a', 'ground-imagery:1');
    port.saveArtifact('a', 'ground-imagery:1', 'artifact:before');
  });
  expect(port.read('a')).toEqual({
    requestId: 'ground-imagery:1',
    artifactId: 'artifact:before',
  });
  expect(result.current.navigationKey).toBe(key);
  expect(result.current.retention).toBe(port);
  expect(window.history.state).toEqual({ marker: 1 });
  expect(window.location.hash).toBe('#context');
  expect(new URLSearchParams(window.location.search).get('scan')).toBe('retained');
  act(() => port.saveRequest('a', 'ground-imagery:2'));
  expect(port.read('a')?.artifactId).toBeUndefined();
  act(() => port.saveArtifact('a', 'ground-imagery:1', 'artifact:stale'));
  expect(port.read('a')?.artifactId).toBeUndefined();
});
it('clears imagery when selecting another event and ignores late saves from the old event', () => {
  window.history.replaceState(null, '', '/?i=a&gr=ground-imagery:1&ga=artifact:before');
  const { result } = renderHook(() => ({
    ...useGroundInspectionLocation(),
    navigation: useWorkspaceNavigation(),
  }));
  act(() => result.current.navigation.openPane('event', 'b'));
  act(() => result.current.retention.saveRequest('a', 'ground-imagery:late'));
  expect(new URLSearchParams(window.location.search).has('gr')).toBe(false);
  expect(new URLSearchParams(window.location.search).has('ga')).toBe(false);
  expect(new URLSearchParams(window.location.search).get('i')).toBe('b');
});
it('restores a different retained inspection on history traversal', () => {
  window.history.replaceState(null, '', '/?i=a&gr=ground-imagery:1');
  const { result } = renderHook(() => useGroundInspectionLocation());
  const key = result.current.navigationKey;
  act(() => {
    window.history.replaceState(
      null,
      '',
      '/?i=a&gr=ground-imagery:2&ga=artifact:after',
    );
    window.dispatchEvent(new PopStateEvent('popstate'));
  });
  expect(result.current.navigationKey).toBe(key + 1);
  expect(result.current.retention.read('a')).toEqual({
    requestId: 'ground-imagery:2',
    artifactId: 'artifact:after',
  });
});
