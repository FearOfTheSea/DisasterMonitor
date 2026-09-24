export type Destination = 'explore' | 'saved' | 'sources' | 'tools';
export type WorkspaceSection =
  | 'watches'
  | 'bookmarks'
  | 'activity'
  | 'field-reports'
  | 'workspace'
  | 'source-health'
  | 'evidence-history'
  | 'maintenance';
export type ExplorePane = 'event' | 'assistant' | 'ground' | null;

export type WorkspaceLocation = {
  destination: Destination;
  section: WorkspaceSection;
  explorePane: ExplorePane;
};

export const DEFAULT_WORKSPACE_LOCATION: WorkspaceLocation = {
  destination: 'explore',
  section: 'watches',
  explorePane: null,
};

const DESTINATIONS = new Set<Destination>(['explore', 'saved', 'sources', 'tools']);
const SECTIONS = new Set<WorkspaceSection>([
  'watches',
  'bookmarks',
  'activity',
  'field-reports',
  'workspace',
  'source-health',
  'evidence-history',
  'maintenance',
]);
const PANES = new Set<Exclude<ExplorePane, null>>(['event', 'assistant', 'ground']);

export function parseWorkspaceLocation(search: string): WorkspaceLocation {
  const parameters = new URLSearchParams(search);
  const destination = parameters.get('w') as Destination;
  const section = parameters.get('sub') as WorkspaceSection;
  const explorePane = parameters.get('pane') as Exclude<ExplorePane, null>;
  return {
    destination: DESTINATIONS.has(destination) ? destination : 'explore',
    section: SECTIONS.has(section) ? section : 'watches',
    explorePane: PANES.has(explorePane) ? explorePane : null,
  };
}

export function serializeWorkspaceLocation(
  search: string,
  state: WorkspaceLocation,
): string {
  const parameters = new URLSearchParams(search);
  if (state.destination === 'explore') parameters.delete('w');
  else parameters.set('w', state.destination);
  if (state.section === 'watches') parameters.delete('sub');
  else parameters.set('sub', state.section);
  if (state.explorePane) parameters.set('pane', state.explorePane);
  else parameters.delete('pane');
  return parameters.toString();
}
