'use client';

import { useEffect, useRef, useState } from 'react';

import type { WorkspaceSection } from './workspaceLocation';
import { sectionLabel, TOOL_SECTIONS } from './workspaceSections';

export function ToolsMenu({
  onSelect,
}: {
  onSelect: (section: WorkspaceSection) => void;
}) {
  const [open, setOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (!open) return;
    containerRef.current
      ?.querySelector<HTMLButtonElement>('[role="menuitem"]')
      ?.focus();
    const dismiss = (event: MouseEvent | KeyboardEvent) => {
      if (event instanceof KeyboardEvent) {
        if (event.key === 'Escape') {
          setOpen(false);
          triggerRef.current?.focus();
        }
      } else if (
        event.target instanceof Node &&
        !containerRef.current?.contains(event.target)
      ) {
        setOpen(false);
      }
    };
    document.addEventListener('mousedown', dismiss);
    document.addEventListener('keydown', dismiss);
    return () => {
      document.removeEventListener('mousedown', dismiss);
      document.removeEventListener('keydown', dismiss);
    };
  }, [open]);

  return (
    <div className="tools-menu-container" ref={containerRef}>
      <button
        ref={triggerRef}
        type="button"
        aria-haspopup="menu"
        aria-controls="tools-menu"
        aria-expanded={open}
        onClick={() => setOpen((current) => !current)}
      >
        Tools
      </button>
      {open && (
        <div
          id="tools-menu"
          className="tools-menu"
          role="menu"
          onKeyDown={(event) => {
            if (event.key === 'Tab') {
              setOpen(false);
              return;
            }
            const items = Array.from(
              event.currentTarget.querySelectorAll<HTMLButtonElement>(
                '[role="menuitem"]',
              ),
            );
            const current = items.indexOf(document.activeElement as HTMLButtonElement);
            const next =
              event.key === 'ArrowDown'
                ? (current + 1) % items.length
                : event.key === 'ArrowUp'
                  ? (current - 1 + items.length) % items.length
                  : event.key === 'Home'
                    ? 0
                    : event.key === 'End'
                      ? items.length - 1
                      : -1;
            if (next < 0) return;
            event.preventDefault();
            items[next]?.focus();
          }}
        >
          {TOOL_SECTIONS.map((section) => (
            <button
              key={section}
              type="button"
              role="menuitem"
              onClick={() => {
                onSelect(section);
                setOpen(false);
              }}
            >
              {sectionLabel(section)}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
