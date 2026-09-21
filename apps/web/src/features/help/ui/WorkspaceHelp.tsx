'use client';

import { useEffect, useRef, useState } from 'react';

export function WorkspaceHelp() {
  const [open, setOpen] = useState(false);
  const trigger = useRef<HTMLButtonElement>(null);

  function close() {
    setOpen(false);
    trigger.current?.focus();
  }

  useEffect(() => {
    if (!open) return;
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === 'Escape') close();
    }
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [open]);

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
        <section
          id="workspace-help-dialog"
          className="workspace-help-dialog"
          role="dialog"
          aria-label="How to use Disaster Monitor"
        >
          <header>
            <div>
              <h2>How to read this workspace</h2>
              <p>Three quick rules for confident decisions.</p>
            </div>
            <button type="button" aria-label="Close help guide" onClick={close}>
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
        </section>
      ) : null}
    </div>
  );
}
