import type { ComponentProps } from 'react';

import { OperationsPanel } from '@/features/operations/ui/OperationsPanel';
import { SourceCatalog } from '@/features/sources/ui/SourceCatalog';

import type { useWorkspaceNavigation } from './useWorkspaceNavigation';
import { workspaceScrollKey } from './useWorkspaceScrollRestoration';
import { SAVED_SECTIONS, sectionLabel, TOOL_SECTIONS } from './workspaceSections';

type Navigation = Pick<
  ReturnType<typeof useWorkspaceNavigation>,
  'destination' | 'section' | 'navigate'
>;

type Props = {
  navigation: Navigation;
  operationsProps: Omit<ComponentProps<typeof OperationsPanel>, 'section'>;
};

export function SecondaryWorkspaces({ navigation, operationsProps }: Props) {
  const { destination, section, navigate } = navigation;
  if (destination === 'sources') {
    return (
      <section className="secondary-workspace" data-workspace-scroll-key="sources">
        <div className="secondary-workspace-inner">
          <SourceCatalog onClose={() => navigate('explore')} />
        </div>
      </section>
    );
  }
  if (destination !== 'saved' && destination !== 'tools') return null;

  const sections = destination === 'saved' ? SAVED_SECTIONS : TOOL_SECTIONS;
  const activeSection = sections.find((item) => item === section) ?? sections[0];
  const label = destination === 'saved' ? 'Saved' : 'Tools';
  return (
    <section
      className="secondary-workspace"
      aria-label={`${label} workspace`}
      data-workspace-scroll-key={workspaceScrollKey(destination, section)}
    >
      <div className="secondary-workspace-inner">
        <nav className="workspace-subnav" aria-label={`${label} sections`}>
          {sections.map((item) => (
            <button
              key={item}
              type="button"
              aria-current={section === item ? 'page' : undefined}
              onClick={() => navigate(destination, item)}
            >
              {sectionLabel(item)}
            </button>
          ))}
        </nav>
        <OperationsPanel {...operationsProps} section={activeSection} />
      </div>
    </section>
  );
}
