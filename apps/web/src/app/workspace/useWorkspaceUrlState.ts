import { useEffect, useRef } from 'react';
import {
  createMapUrlStateHistory,
  type MapUrlState,
  type MapUrlStateHistory,
} from '@/features/map/model/mapUrlState';

export function useWorkspaceUrlState(
  defaultUrlState: MapUrlState,
  state: MapUrlState,
  onRestore: (state: MapUrlState) => void,
) {
  const mapUrlHistory = useRef<MapUrlStateHistory | undefined>(undefined);
  const skipNextUrlWrite = useRef(false);
  useEffect(() => {
    let initialRestore = true;
    const history = createMapUrlStateHistory(
      defaultUrlState,
      (restored) => {
        if (initialRestore) {
          initialRestore = false;
          const parameters = new URLSearchParams(window.location.search);
          if (
            !['c', 'z', 'b', 'r', 'i', 'l', 't', 's', 'o'].some((key) =>
              parameters.has(key),
            )
          ) {
            return;
          }
        }
        skipNextUrlWrite.current = true;
        onRestore(restored);
      },
      window,
    );
    mapUrlHistory.current = history;
    history.start();
    return () => {
      history.stop();
      mapUrlHistory.current = undefined;
    };
  }, [defaultUrlState, onRestore]);

  useEffect(() => {
    if (skipNextUrlWrite.current) {
      skipNextUrlWrite.current = false;
      return;
    }
    mapUrlHistory.current?.schedule(state);
  }, [state]);
}
