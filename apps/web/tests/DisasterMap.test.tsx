import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import type { ActiveIncident } from '@/features/incidents/model/activeIncidents';
import { DisasterMap } from '@/features/map/ui/DisasterMap';

const adapterMocks = vi.hoisted(() => ({
  destroy: vi.fn(),
  fitArea: vi.fn(),
  focusActiveIncident: vi.fn(),
  onSelectIncident: undefined as ((incidentId: string) => void) | undefined,
  setActiveIncidents: vi.fn(),
  setCommonOperationalPicture: vi.fn(),
  setSatelliteImagery: vi.fn(),
  setSatelliteOpacity: vi.fn(),
  setSelectedIncident: vi.fn(),
}));

const satelliteClientMocks = vi.hoisted(() => ({
  fetchCatalog: vi.fn(),
}));

vi.mock('@/features/map/api/satelliteImageryClient', async (importOriginal) => {
  const original =
    await importOriginal<typeof import('@/features/map/api/satelliteImageryClient')>();
  return {
    ...original,
    fetchSatelliteImageryCatalog: satelliteClientMocks.fetchCatalog,
  };
});

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
    setSatelliteImagery = adapterMocks.setSatelliteImagery;
    setSatelliteOpacity = adapterMocks.setSatelliteOpacity;
    setSelectedIncident = adapterMocks.setSelectedIncident;
  },
}));

describe('DisasterMap assistant focus', () => {
  afterEach(cleanup);

  beforeEach(() => {
    vi.clearAllMocks();
    satelliteClientMocks.fetchCatalog.mockResolvedValue([
      { sourceId: 'nasa-viirs-snpp-true-color', available: true },
      { sourceId: 'nasa-modis-terra-true-color', available: true },
      { sourceId: 'nasa-modis-aqua-true-color', available: true },
      { sourceId: 'nasa-goes-east-geocolor', available: true },
      { sourceId: 'nasa-goes-west-geocolor', available: true },
      { sourceId: 'nasa-himawari-9-visible', available: true },
      { sourceId: 'copernicus-sentinel-2-true-color', available: false },
      { sourceId: 'planet-configured-mosaic', available: false },
    ]);
  });

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

  it('switches the one satellite layer and preserves daily versus UTC controls', async () => {
    const user = userEvent.setup();
    render(<DisasterMap onViewChange={vi.fn()} onSelectIncident={vi.fn()} />);

    await user.click(screen.getByRole('checkbox', { name: 'Satellite imagery' }));
    await waitFor(() =>
      expect(adapterMocks.setSatelliteImagery).toHaveBeenLastCalledWith(
        expect.objectContaining({
          sourceId: 'nasa-viirs-snpp-true-color',
          url: expect.stringContaining('VIIRS_SNPP_CorrectedReflectance_TrueColor'),
        }),
      ),
    );
    expect(screen.getByLabelText('Observation date')).toHaveAttribute('type', 'date');

    await user.selectOptions(
      screen.getByLabelText('Satellite source'),
      'nasa-goes-east-geocolor',
    );
    const utcInput = screen.getByLabelText('Observation date/time (UTC)');
    expect(utcInput).toHaveAttribute('type', 'datetime-local');
    expect(utcInput).toHaveAttribute('step', '600');
    fireEvent.change(utcInput, { target: { value: '2026-08-20T12:20' } });
    await waitFor(() =>
      expect(adapterMocks.setSatelliteImagery).toHaveBeenLastCalledWith(
        expect.objectContaining({
          sourceId: 'nasa-goes-east-geocolor',
          url: expect.stringContaining('2026-08-20T12:20:00Z'),
        }),
      ),
    );

    const activeLayers = adapterMocks.setSatelliteImagery.mock.calls
      .map(([configuration]) => configuration)
      .filter(Boolean);
    expect(activeLayers.at(-1)).toMatchObject({ sourceId: 'nasa-goes-east-geocolor' });
    expect(screen.getByText(/Imagery is not live/i)).toBeVisible();
    expect(screen.getByText(/Requested observation:/i)).toHaveTextContent(
      '2026-08-20T12:20:00Z',
    );
  });

  it('updates imagery opacity and turns the satellite layer off', async () => {
    const user = userEvent.setup();
    render(<DisasterMap onViewChange={vi.fn()} onSelectIncident={vi.fn()} />);

    await user.click(screen.getByRole('checkbox', { name: 'Satellite imagery' }));
    fireEvent.change(screen.getByLabelText('Satellite opacity'), {
      target: { value: '0.4' },
    });
    expect(adapterMocks.setSatelliteOpacity).toHaveBeenLastCalledWith(0.4);

    await user.click(screen.getByRole('checkbox', { name: 'Satellite imagery' }));
    expect(adapterMocks.setSatelliteImagery).toHaveBeenLastCalledWith(undefined);
  });

  it('disables unavailable credentialed provider options without failing the map', async () => {
    render(<DisasterMap onViewChange={vi.fn()} onSelectIncident={vi.fn()} />);

    await waitFor(() => expect(satelliteClientMocks.fetchCatalog).toHaveBeenCalled());
    expect(
      screen.getByRole('option', { name: 'Copernicus Sentinel-2 True Color' }),
    ).toBeDisabled();
    expect(
      screen.getByRole('option', { name: 'Planet configured mosaic' }),
    ).toBeDisabled();
    expect(screen.getByLabelText('Interactive map')).toBeInTheDocument();
  });
});
