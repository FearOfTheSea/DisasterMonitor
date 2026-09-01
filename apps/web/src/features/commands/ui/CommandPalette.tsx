'use client';

import {
  type KeyboardEvent as ReactKeyboardEvent,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react';

import type { OperatorCommand } from '@/features/commands/model/commandRegistry';

type CommandPaletteProps = {
  commands: readonly OperatorCommand[];
};

function normalized(value: string): string {
  return value.trim().toLocaleLowerCase();
}

export function CommandPalette({ commands }: CommandPaletteProps) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState('');
  const [activeIndex, setActiveIndex] = useState(0);
  const input = useRef<HTMLInputElement>(null);
  const dialog = useRef<HTMLDivElement>(null);
  const restoreFocus = useRef<HTMLElement | null>(null);
  const filtered = useMemo(() => {
    const term = normalized(query);
    if (!term) return commands;
    return commands.filter((command) =>
      normalized([command.label, ...command.keywords].join(' ')).includes(term),
    );
  }, [commands, query]);

  function show() {
    restoreFocus.current =
      document.activeElement instanceof HTMLElement ? document.activeElement : null;
    setQuery('');
    setActiveIndex(0);
    setOpen(true);
  }

  function close() {
    setOpen(false);
    restoreFocus.current?.focus();
  }

  function execute(command: OperatorCommand) {
    command.execute();
    close();
  }

  useEffect(() => {
    function onShortcut(event: KeyboardEvent) {
      if ((event.ctrlKey || event.metaKey) && event.key.toLocaleLowerCase() === 'k') {
        event.preventDefault();
        show();
      }
    }
    window.addEventListener('keydown', onShortcut);
    return () => window.removeEventListener('keydown', onShortcut);
  }, []);

  useEffect(() => {
    if (open) input.current?.focus();
  }, [open]);

  function onInputKeyDown(event: ReactKeyboardEvent<HTMLInputElement>) {
    if (event.key === 'ArrowDown') {
      event.preventDefault();
      setActiveIndex((index) =>
        filtered.length === 0 ? 0 : (index + 1) % filtered.length,
      );
    } else if (event.key === 'ArrowUp') {
      event.preventDefault();
      setActiveIndex((index) =>
        filtered.length === 0 ? 0 : (index - 1 + filtered.length) % filtered.length,
      );
    } else if (event.key === 'Enter') {
      event.preventDefault();
      const command = filtered[activeIndex] ?? filtered[0];
      if (command) execute(command);
    } else if (event.key === 'Escape') {
      event.preventDefault();
      close();
    }
  }

  function trapFocus(event: ReactKeyboardEvent<HTMLDivElement>) {
    if (event.key === 'Escape') {
      event.preventDefault();
      close();
      return;
    }
    if (event.key !== 'Tab' || !dialog.current) return;
    const focusable = [
      ...dialog.current.querySelectorAll<HTMLElement>('input, button:not(:disabled)'),
    ];
    const first = focusable[0];
    const last = focusable.at(-1);
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last?.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first?.focus();
    }
  }

  return (
    <>
      <button type="button" className="command-palette-trigger" onClick={show}>
        Commands <kbd>⌘/Ctrl K</kbd>
      </button>
      {open ? (
        <div className="command-palette-backdrop">
          <div
            ref={dialog}
            className="command-palette"
            role="dialog"
            aria-modal="true"
            aria-label="Command palette"
            onKeyDown={trapFocus}
          >
            <header>
              <label htmlFor="command-palette-search">Search commands</label>
              <button type="button" onClick={close} aria-label="Close command palette">
                Escape
              </button>
            </header>
            <input
              id="command-palette-search"
              ref={input}
              role="combobox"
              aria-label="Search commands"
              aria-controls="command-palette-results"
              aria-expanded="true"
              aria-autocomplete="list"
              value={query}
              onChange={(event) => {
                setQuery(event.target.value);
                setActiveIndex(0);
              }}
              onKeyDown={onInputKeyDown}
            />
            <div id="command-palette-results" role="listbox">
              {filtered.map((command, index) => (
                <button
                  type="button"
                  role="option"
                  aria-label={command.label}
                  aria-selected={index === activeIndex}
                  key={command.id}
                  onMouseEnter={() => setActiveIndex(index)}
                  onClick={() => execute(command)}
                >
                  <span>{command.label}</span>
                  <small>{command.group}</small>
                </button>
              ))}
              {filtered.length === 0 ? (
                <p>No registered commands match this query.</p>
              ) : null}
            </div>
          </div>
        </div>
      ) : null}
    </>
  );
}
