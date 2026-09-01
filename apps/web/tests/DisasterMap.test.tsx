import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import type { ActiveIncident } from '@/features/incidents/model/activeIncidents';
import { DisasterMap } from '@/features/map/ui/DisasterMap';
import type { WeatherAlertsSnapshot } from '@/features/weather/model/weatherAlert';
import type { MapView, SelectedEvent } from '@/shared/types/assistant';

const adapterMocks = vi.hoisted(() => ({
  destroy: vi.fn(),
  fitArea: vi.fn(),
  focusActiveIncident: vi.fn(),
  onViewChange: undefined as ((view: MapView) => void) | undefined,
  onSelectIncidentCluster: undefined as ((incidentIds: string[]) => void) | undefined,
  onSelectIncident: undefined as ((incidentId: string) => void) | undefined,
  setActiveIncidents: vi.fn(),
  setCommonOperationalPicture: vi.fn(),
  setCycloneMapLayers: vi.fn(),
  setLayerVisibility: vi.fn(),
  setSatelliteImagery: vi.fn(),
  setSatelliteOpacity: vi.fn(),
  setSelectedIncident: vi.fn(),
  setView: vi.fn(),
  setWeatherAlerts: vi.fn(),
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
    constructor(options: {
      onViewChange: (view: MapView) => void;
      onSelectIncident: (incidentId: string) => void;
      onSelectIncidentCluster?: (incidentIds: string[]) => void;
    }) {
      adapterMocks.onViewChange = options.onViewChange;
      adapterMocks.onSelectIncident = options.onSelectIncident;
      adapterMocks.onSelectIncidentCluster = options.onSelectIncidentCluster;
    }

    destroy = adapterMocks.destroy;
    fitArea = adapterMocks.fitArea;
    focusActiveIncident = adapterMocks.focusActiveIncident;
    setActiveIncidents = adapterMocks.setActiveIncidents;
    setCommonOperationalPicture = adapterMocks.setCommonOperationalPicture;
    setCycloneMapLayers = adapterMocks.setCycloneMapLayers;
    setLayerVisibility = adapterMocks.setLayerVisibility;
    setSatelliteImagery = adapterMocks.setSatelliteImagery;
    setSatelliteOpacity = adapterMocks.setSatelliteOpacity;
    setSelectedIncident = adapterMocks.setSelectedIncident;
    setView = adapterMocks.setView;
    setWeatherAlerts = adapterMocks.setWeatherAlerts;
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

  it('does not reapply a view that the map has just reported', () => {
    const initialView = { centerLatitude: 21.03, centerLongitude: 105.85, zoom: 10 };
    const reportedView = { centerLatitude: 37.02, centerLongitude: 137.01, zoom: 10 };
    const { rerender } = render(
      <DisasterMap
        onViewChange={vi.fn()}
        onSelectIncident={vi.fn()}
        view={initialView}
      />,
    );

    adapterMocks.setView.mockClear();
    adapterMocks.onViewChange?.(reportedView);
    rerender(
      <DisasterMap
        onViewChange={vi.fn()}
        onSelectIncident={vi.fn()}
        view={reportedView}
      />,
    );

    expect(adapterMocks.setView).not.toHaveBeenCalled();
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

  it('lets an operator choose every canonical incident exposed by a cluster', async () => {
    const user = userEvent.setup();
    const onSelectIncident = vi.fn();
    const source = {
      source_id: 'fixture-source',
      publisher: 'Fixture publisher',
      title: 'Fixture source',
      canonical_url: 'https://example.test/incidents',
      published_at: '2026-08-20T02:00:00Z',
      updated_at: null,
      retrieved_at: '2026-08-20T04:00:00Z',
      snapshot_id: null,
    };
    const incidents: ActiveIncident[] = ['first', 'second'].map((eventId, index) => ({
      event_id: eventId,
      disaster: 'earthquake',
      location: `${eventId} location`,
      event_time: '2026-08-20T03:00:00Z',
      geometry: {
        kind: 'point',
        coordinates: [{ latitude: 10 + index / 100, longitude: 20 }],
        description: null,
        source_id: source.source_id,
        estimated: false,
      },
      measurements: [],
      provider_ids: [`fixture:${eventId}`],
      provider_tier: 'primary',
      source_authority: 'scientific_authority',
      source,
    }));
    render(
      <DisasterMap
        onViewChange={vi.fn()}
        onSelectIncident={onSelectIncident}
        activeIncidents={incidents}
      />,
    );

    act(() => adapterMocks.onSelectIncidentCluster?.(['first', 'second']));

    expect(
      screen.getByRole('complementary', { name: 'Clustered incidents' }),
    ).toBeVisible();
    await user.click(screen.getByRole('button', { name: 'second location' }));
    expect(onSelectIncident).toHaveBeenCalledWith('second');
    expect(
      screen.queryByRole('complementary', { name: 'Clustered incidents' }),
    ).not.toBeInTheDocument();
  });

  it('renders distinct cyclone layer semantics and clears stale layers', () => {
    const source = {
      source_id: 'noaa-nhc-cyclone-forecast',
      publisher: 'NOAA NHC/CPHC',
      title: 'Advisory products',
      canonical_url: 'https://www.nhc.noaa.gov/fixture.kmz',
      published_at: '2026-08-31T03:00:00Z',
      updated_at: '2026-08-31T03:00:00Z',
      retrieved_at: '2026-08-31T03:05:00Z',
      snapshot_id: null,
    };
    const selectedEvent: SelectedEvent = {
      event_id: 'gdacs:tc:42',
      disaster: 'tropical_cyclone',
      location: 'Pacific Ocean',
      event_time: '2026-08-31T03:00:00Z',
      geometry: null,
      measurements: [],
      provider_ids: ['atcf:EP112026'],
      geography_status: 'worldwide',
      source,
      supplemental_geometry: [
        {
          layer_id: 'provisional',
          semantic_role: 'provisional_track',
          geometry_kind: 'track',
          coordinates: [
            { latitude: 16, longitude: -122, valid_at: '2026-08-30T12:00:00Z' },
            { latitude: 17, longitude: -124, valid_at: '2026-08-31T00:00:00Z' },
          ],
          source,
          issued_at: '2026-08-31T00:00:00Z',
          valid_from: '2026-08-30T12:00:00Z',
          valid_to: '2026-08-31T00:00:00Z',
          storm_id: 'EP112026',
          provisional: true,
          limitation: 'Provisional best-track context, not a forecast.',
          reconciliation: 'Unique identity match.',
          wind_threshold: null,
          wind_threshold_unit: null,
        },
        {
          layer_id: 'forecast',
          semantic_role: 'forecast_track',
          geometry_kind: 'track',
          coordinates: [
            { latitude: 17.2, longitude: -124.4, valid_at: '2026-08-31T12:00:00Z' },
            { latitude: 17.8, longitude: -127, valid_at: '2026-09-01T00:00:00Z' },
          ],
          source,
          issued_at: '2026-08-31T03:00:00Z',
          valid_from: '2026-08-31T12:00:00Z',
          valid_to: '2026-09-01T00:00:00Z',
          storm_id: 'EP112026',
          provisional: false,
          limitation: 'Forecast positions are not an observed storm footprint.',
          reconciliation: 'Unique identity match.',
          wind_threshold: null,
          wind_threshold_unit: null,
        },
        {
          layer_id: 'cone',
          semantic_role: 'uncertainty_area',
          geometry_kind: 'area',
          coordinates: [
            { latitude: 16, longitude: -124, valid_at: null },
            { latitude: 16, longitude: -130, valid_at: null },
            { latitude: 20, longitude: -130, valid_at: null },
          ],
          source,
          issued_at: '2026-08-31T03:00:00Z',
          valid_from: '2026-08-31T03:00:00Z',
          valid_to: '2026-09-05T03:00:00Z',
          storm_id: 'EP112026',
          provisional: false,
          limitation: 'The cone is not an observed storm footprint.',
          reconciliation: 'Unique identity match.',
          wind_threshold: null,
          wind_threshold_unit: null,
        },
      ],
    };

    const { rerender } = render(
      <DisasterMap
        onViewChange={vi.fn()}
        onSelectIncident={vi.fn()}
        selectedEvent={selectedEvent}
      />,
    );

    expect(adapterMocks.setCycloneMapLayers).toHaveBeenCalledWith(
      selectedEvent.supplemental_geometry,
    );
    expect(
      screen
        .getByText('Provisional track')
        .closest('li')
        ?.querySelector('.cyclone-legend-mark'),
    ).toHaveClass('cyclone-legend-provisional_track');
    expect(
      screen
        .getByText('Forecast track')
        .closest('li')
        ?.querySelector('.cyclone-legend-mark'),
    ).toHaveClass('cyclone-legend-forecast_track');
    expect(
      screen
        .getByText('Forecast uncertainty')
        .closest('li')
        ?.querySelector('.cyclone-legend-mark'),
    ).toHaveClass('cyclone-legend-uncertainty_area');
    expect(
      screen.getByText(
        'Forecast and uncertainty geometry are not observed storm footprints.',
      ),
    ).toBeVisible();

    rerender(
      <DisasterMap
        onViewChange={vi.fn()}
        onSelectIncident={vi.fn()}
        selectedEvent={{
          ...selectedEvent,
          event_id: 'earthquake-1',
          disaster: 'earthquake',
          supplemental_geometry: [],
        }}
      />,
    );
    expect(adapterMocks.setCycloneMapLayers).toHaveBeenLastCalledWith([]);
    expect(screen.queryByText('Forecast track')).not.toBeInTheDocument();
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

  it('passes only source weather alert geometry to its layer and labels alert semantics', () => {
    const snapshot: WeatherAlertsSnapshot = {
      retrieved_at: '2026-09-01T02:00:00Z',
      alerts: [
        {
          provider_alert_id: 'alert-1',
          source_id: 'nws-weather-alerts',
          publisher: 'NOAA/National Weather Service',
          event: 'Tornado Warning',
          headline: 'Tornado Warning issued September 1',
          severity: 'extreme',
          urgency: 'immediate',
          certainty: 'observed',
          sent: '2026-09-01T01:45:00Z',
          effective: '2026-09-01T01:45:00Z',
          onset: '2026-09-01T01:45:00Z',
          expires: '2026-09-01T02:30:00Z',
          affected_area: 'Fixture County',
          geometry: {
            kind: 'polygon',
            rings: [
              [
                { latitude: 35, longitude: -98 },
                { latitude: 36, longitude: -98 },
                { latitude: 35, longitude: -98 },
              ],
            ],
          },
          canonical_url: 'https://api.weather.gov/alerts/urn:fixture',
          retrieved_at: '2026-09-01T02:00:00Z',
          attribution: 'NOAA/National Weather Service',
          limitations: [],
        },
      ],
      coverage: {
        source_id: 'nws-weather-alerts',
        publisher: 'NOAA/National Weather Service',
        state: 'alerts_found',
        detail: 'One active alert was returned.',
        geographic_scope: 'United States land areas served by NWS.',
        limitations: [],
      },
      warnings: [],
    };

    render(
      <DisasterMap
        onViewChange={vi.fn()}
        onSelectIncident={vi.fn()}
        weatherAlerts={snapshot}
      />,
    );

    expect(adapterMocks.setWeatherAlerts).toHaveBeenLastCalledWith(snapshot.alerts);
    expect(
      screen.getByRole('complementary', { name: 'Weather alert coverage' }),
    ).toHaveTextContent(
      'official warning areas, not observed disaster event footprints',
    );
    expect(screen.getByText('Tornado Warning')).toBeVisible();
  });
});
