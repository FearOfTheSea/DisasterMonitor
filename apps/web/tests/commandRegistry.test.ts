import { describe, expect, it, vi } from 'vitest';

import { buildCommandRegistry } from '@/features/commands/model/commandRegistry';
import { createDefaultMapLayerState } from '@/features/map/model/mapLayerState';

describe('command registry', () => {
  it('builds a deterministic in-memory index from registered UI state only', () => {
    const selectIncident = vi.fn();
    const context = {
      incidents: [
        {
          event_id: 'fixture-1',
          location: 'Fixture Valley',
          source: { title: 'Fixture event title' },
        },
      ],
      layerState: createDefaultMapLayerState(),
      selectedIncidentId: 'fixture-1',
      onSelectIncident: selectIncident,
      onFocusSelectedIncident: vi.fn(),
      onSelectRegion: vi.fn(),
      onLayerStateChange: vi.fn(),
      onOpenFindings: vi.fn(),
      onOpenSourceCatalog: vi.fn(),
      onOpenIncidentWatches: vi.fn(),
      onOpenOperations: vi.fn(),
    };

    const first = buildCommandRegistry(context);
    const second = buildCommandRegistry(context);

    expect(first.map((command) => command.id)).toEqual(
      second.map((command) => command.id),
    );
    expect(new Set(first.map((command) => command.id)).size).toBe(first.length);
    const incident = first.find((command) => command.id === 'incident:fixture-1');
    expect(incident?.label).toMatch(/Fixture event title.*Fixture Valley/);
    incident?.execute();
    expect(selectIncident).toHaveBeenCalledWith('fixture-1');
    expect(first.some((command) => command.id.includes('qwen'))).toBe(false);
  });
});
