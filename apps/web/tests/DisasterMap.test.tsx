import { render } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import type { ActiveIncident } from '@/features/incidents/model/activeIncidents';
import { DisasterMap } from '@/features/map/ui/DisasterMap';

const adapterMocks = vi.hoisted(() => ({
  destroy: vi.fn(),
  fitArea: vi.fn(),
  focusActiveIncident: vi.fn(),
  onSelectIncident: undefined as ((incidentId: string) => void) | undefined,
  setActiveIncidents: vi.fn(),
  setCommonOperationalPicture: vi.fn(),
  setSelectedIncident: vi.fn(),
}));

vi.mock('@/features/map/adapters/openLayersMapAdapter', () => ({
  OpenLayersMapAdapter: class {
    constructor(options: { onSelectIncident: (incidentId: string) => void }) {
      adapterMocks.onSelectIncident = options.onSelectIncident;
    }

    destroy = adapterMocks.destroy;
    fitArea = adapterMocks.fitArea;
    focusActiveIncident = adapterMocks.focusActiveIncident;
    setActiveIncidents = adapterMocks.setActiveIncidents;
    setCommonOperationalPicture = adapterMocks.setCommonOperationalPicture;
    setSelectedIncident = adapterMocks.setSelectedIncident;
  },
}));

describe('DisasterMap assistant focus', () => {
  beforeEach(() => vi.clearAllMocks());

  it('fits each logical area once and refits when its bounds change', () => {
    const onViewChange = vi.fn();
    const onSelectIncident = vi.fn();
    const { rerender, unmount } = render(
      <DisasterMap
        onViewChange={onViewChange}
        onSelectIncident={onSelectIncident}
        areaOfInterest={{ id: 'assistant-1:event:event-1', bounds: [137, 37, 137, 37] }}
      />,
    );

    expect(adapterMocks.fitArea).toHaveBeenCalledTimes(1);
    expect(adapterMocks.fitArea).toHaveBeenLastCalledWith([137, 37, 137, 37], 10);

    rerender(
      <DisasterMap
        onViewChange={onViewChange}
        onSelectIncident={onSelectIncident}
        areaOfInterest={{ id: 'assistant-1:event:event-1', bounds: [137, 37, 137, 37] }}
      />,
    );
    expect(adapterMocks.fitArea).toHaveBeenCalledTimes(1);

    rerender(
      <DisasterMap
        onViewChange={onViewChange}
        onSelectIncident={onSelectIncident}
        areaOfInterest={{
          id: 'assistant-1:event:event-1',
          bounds: [136, 36, 138, 38],
          maxZoom: 8,
        }}
      />,
    );
    expect(adapterMocks.fitArea).toHaveBeenCalledTimes(2);
    expect(adapterMocks.fitArea).toHaveBeenLastCalledWith([136, 36, 138, 38], 8);

    unmount();
    expect(adapterMocks.destroy).toHaveBeenCalledTimes(1);
  });

  it('hands exact renderable incident geometries to a distinct map layer', () => {
    const source = {
      source_id: 'fixture-source',
      publisher: 'Fixture publisher',
      title: 'Fixture source',
      canonical_url: 'https://example.test/incidents',
      published_at: '2026-08-20T02:00:00Z',
      updated_at: '2026-08-20T03:00:00Z',
      retrieved_at: '2026-08-20T04:00:00Z',
      snapshot_id: null,
    };
    const pointGeometry = {
      kind: 'point' as const,
      coordinates: [{ latitude: 10.5, longitude: 20.25 }],
      description: null,
      source_id: source.source_id,
      estimated: false,
    };
    const areaGeometry = {
      kind: 'area' as const,
      coordinates: [
        { latitude: 1, longitude: 2 },
        { latitude: 3, longitude: 4 },
        { latitude: 5, longitude: 6 },
      ],
      description: null,
      source_id: source.source_id,
      estimated: false,
    };
    const incidents: ActiveIncident[] = [
      {
        event_id: 'point-1',
        disaster: 'earthquake',
        location: 'Point event',
        event_time: '2026-08-20T03:00:00Z',
        geometry: pointGeometry,
        measurements: [],
        provider_ids: [],
        provider_tier: 'secondary',
        source_authority: 'scientific_authority',
        source,
      },
      {
        event_id: 'flood-1',
        disaster: 'flood',
        location: 'Estimated flood tile',
        event_time: '2026-08-20T02:30:00Z',
        geometry: {
          kind: 'point',
          coordinates: [{ latitude: 32.5, longitude: 133.5 }],
          description: null,
          source_id: source.source_id,
          estimated: true,
        },
        measurements: [],
        provider_ids: [],
        provider_tier: 'primary',
        source_authority: 'scientific_authority',
        source,
      },
      {
        event_id: 'area-1',
        disaster: 'wildfire',
        location: 'Area event',
        event_time: '2026-08-20T02:00:00Z',
        geometry: areaGeometry,
        measurements: [],
        provider_ids: [],
        provider_tier: 'primary',
        source_authority: 'secondary',
        source,
      },
      {
        event_id: 'descriptive-1',
        disaster: 'flood',
        location: 'Descriptive event',
        event_time: '2026-08-20T01:00:00Z',
        geometry: {
          kind: 'descriptive',
          coordinates: [],
          description: 'Provider supplied location text',
          source_id: source.source_id,
          estimated: false,
        },
        measurements: [],
        provider_ids: [],
        provider_tier: 'primary',
        source_authority: 'scientific_authority',
        source,
      },
    ];

    render(
      <DisasterMap
        onViewChange={vi.fn()}
        onSelectIncident={vi.fn()}
        activeIncidents={incidents}
        selectedIncidentId="area-1"
      />,
    );

    expect(adapterMocks.setActiveIncidents).toHaveBeenCalledWith([
      { incidentId: 'point-1', disaster: 'earthquake', geometry: pointGeometry },
      {
        incidentId: 'flood-1',
        disaster: 'flood',
        geometry: incidents[1].geometry,
      },
      { incidentId: 'area-1', disaster: 'wildfire', geometry: areaGeometry },
    ]);
    expect(adapterMocks.focusActiveIncident).toHaveBeenCalledWith('area-1');
    expect(adapterMocks.setSelectedIncident).toHaveBeenCalledWith('area-1');
  });

  it('selects the corresponding incident when a map feature is clicked', () => {
    const onSelectIncident = vi.fn();
    render(<DisasterMap onViewChange={vi.fn()} onSelectIncident={onSelectIncident} />);

    adapterMocks.onSelectIncident?.('flood-1');

    expect(onSelectIncident).toHaveBeenCalledWith('flood-1');
  });
});
