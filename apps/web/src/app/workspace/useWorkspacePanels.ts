import { useCallback, useEffect, useState } from 'react';

type WorkspacePanel = 'assistant' | 'operations' | 'sources';
type PanelState = { panel: WorkspacePanel | null; headingId?: string };

export function useWorkspacePanels() {
  const [state, setState] = useState<PanelState>({ panel: null });
  const togglePanel = useCallback((panel: WorkspacePanel) => {
    setState((current) => ({ panel: current.panel === panel ? null : panel }));
  }, []);
  const closePanel = useCallback(() => setState({ panel: null }), []);
  const openOperationsAt = useCallback(
    (headingId?: string) => setState({ panel: 'operations', headingId }),
    [],
  );
  const openSourceCatalog = useCallback(() => setState({ panel: 'sources' }), []);
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
  };
}
