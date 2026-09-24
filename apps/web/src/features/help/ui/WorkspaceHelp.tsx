'use client';

import { useEffect, useRef, useState } from 'react';

export function WorkspaceHelp({ onSearchCommands }: { onSearchCommands?: () => void }) {
  const [open, setOpen] = useState(false);
  const trigger = useRef<HTMLButtonElement>(null);
  const dialog = useRef<HTMLElement>(null);
  const closeButton = useRef<HTMLButtonElement>(null);

  function close() {
    setOpen(false);
    trigger.current?.focus();
  }

  useEffect(() => {
    if (!open) return;
    closeButton.current?.focus();
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === 'Escape') close();
    }
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [open]);

  function handleDialogKeyDown(event: React.KeyboardEvent<HTMLElement>) {
    if (event.key !== 'Tab' || !dialog.current) return;
    const controls = [
      ...dialog.current.querySelectorAll<HTMLElement>('button:not(:disabled), a[href]'),
    ];
    const first = controls[0];
    const last = controls.at(-1);
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last?.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first?.focus();
    }
  }

  return (
    <div className="workspace-help">
      <button
        ref={trigger}
        type="button"
        className="workspace-help-trigger"
        aria-label={open ? 'Close help' : 'Open help'}
        aria-expanded={open}
        aria-controls="workspace-help-dialog"
        onClick={() => setOpen((current) => !current)}
      >
        <svg className="button-icon" viewBox="0 0 24 24" aria-hidden="true">
          <circle cx="12" cy="12" r="9" />
          <path d="M9.8 9a2.3 2.3 0 1 1 3.6 1.9c-.9.6-1.4 1-1.4 2.1" />
          <path d="M12 17h.01" />
        </svg>
        Help
      </button>
      {open ? (
        <div className="workspace-help-backdrop" onMouseDown={close}>
          <section
            ref={dialog}
            id="workspace-help-dialog"
            className="workspace-help-dialog"
            role="dialog"
            aria-modal="true"
            aria-label="How to use Disaster Monitor"
            onMouseDown={(event) => event.stopPropagation()}
            onKeyDown={handleDialogKeyDown}
          >
            <header>
              <div>
                <h2>How to read this workspace</h2>
                <p>Three quick rules for confident decisions.</p>
              </div>
              <button
                ref={closeButton}
                type="button"
                aria-label="Close help guide"
                onClick={close}
              >
                <svg viewBox="0 0 24 24" aria-hidden="true">
                  <path d="m6 6 12 12M18 6 6 18" />
                </svg>
              </button>
            </header>
            <ol>
              <li>
                <strong>Start with the incident list.</strong>
                Select a row to focus the map and reveal its evidence summary.
              </li>
              <li>
                <strong>Coverage describes source checks.</strong>
                An empty result never proves that no disaster occurred.
              </li>
              <li>
                <strong>Map options change only what is displayed.</strong>
                They do not change provider coverage or source records.
              </li>
            </ol>
            <p>
              Tip: press <kbd>Ctrl K</kbd> to search commands, places, and events.
            </p>
            {onSearchCommands ? (
              <button
                type="button"
                className="help-search-commands"
                onClick={() => {
                  close();
                  onSearchCommands();
                }}
              >
                Search commands
              </button>
            ) : null}
          </section>
        </div>
      ) : null}
    </div>
  );
}
