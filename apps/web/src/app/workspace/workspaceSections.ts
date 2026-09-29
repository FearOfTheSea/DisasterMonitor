import type { WorkspaceSection } from './workspaceLocation';

export const SAVED_SECTIONS = ['watches', 'bookmarks', 'activity'] as const;
export const TOOL_SECTIONS = [
  'field-reports',
  'workspace',
  'source-health',
  'evidence-history',
  'maintenance',
] as const;

export function sectionLabel(section: WorkspaceSection): string {
  return section.replaceAll('-', ' ').replace(/^./, (letter) => letter.toUpperCase());
}
