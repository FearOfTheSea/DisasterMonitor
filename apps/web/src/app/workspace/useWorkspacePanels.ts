import { useCallback, useEffect, useRef, useState } from 'react';

type WorkspacePanel = 'assistant' | 'operations' | 'sources' | 'imagery';
type PanelState = { panel: WorkspacePanel | null; headingId?: string };

export function useWorkspacePanels() {
  const [state, setState] = useState<PanelState>({ panel: null });
  const previousPanel = useRef<WorkspacePanel | null>(null);
  const returnFocusTarget = useRef<HTMLElement | null>(null);
  const togglePanel = useCallback((panel: WorkspacePanel) => {
    setState((current) => ({ panel: current.panel === panel ? null : panel }));
  }, []);
  const closePanel = useCallback(() => setState({ panel: null }), []);
  const openOperationsAt = useCallback(
    (headingId?: string) => setState({ panel: 'operations', headingId }),
    [],
  );
  const openSourceCatalog = useCallback(() => setState({ panel: 'sources' }), []);
  const openGroundImagery = useCallback(() => setState({ panel: 'imagery' }), []);
  useEffect(() => {
    const panelWasOpen = previousPanel.current !== null;
    previousPanel.current = state.panel;
    if (state.panel) {
      const timer = window.setTimeout(() => {
        const activeElement = document.activeElement;
        const isPanelControl = activeElement?.closest(
          '#assistant-panel, #operations-panel, #source-catalog-panel, #ground-imagery-panel',
        );
        if (activeElement instanceof HTMLElement && !isPanelControl) {
          returnFocusTarget.current = activeElement;
        }
      }, 0);
      return () => window.clearTimeout(timer);
    }
    if (panelWasOpen) {
      const timer = window.setTimeout(() => returnFocusTarget.current?.focus(), 0);
      return () => window.clearTimeout(timer);
    }
  }, [state.panel]);
  useEffect(() => {
    if (!state.headingId) return;
    const headingId = state.headingId;
    const timer = window.setTimeout(
      () => document.getElementById(headingId)?.focus(),
      0,
    );
    return () => window.clearTimeout(timer);
  }, [state]);
  return {
    activePanel: state.panel,
    togglePanel,
    closePanel,
    openOperationsAt,
    openSourceCatalog,
    openGroundImagery,
  };
}
