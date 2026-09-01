'use client';

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import 'ol/ol.css';

import {
  OpenLayersMapAdapter,
  type SatelliteLayerConfiguration,
} from '@/features/map/adapters/openLayersMapAdapter';
import type { ActiveIncident } from '@/features/incidents/model/activeIncidents';
import type { AssistantMapAreaOfInterest } from '@/features/map/model/assistantMapFocus';
import { activeIncidentMapFeatures } from '@/features/map/model/activeIncidentMap';
import { copStyleSemantics } from '@/features/map/model/copRenderPlan';
import {
  cycloneMapLayers,
  cycloneStyleSemantics,
} from '@/features/map/model/cycloneMapLayers';
import { DEFAULT_MAP_VIEW } from '@/features/map/model/mapView';
import {
  createDefaultMapLayerState,
  type MapLayerState,
} from '@/features/map/model/mapLayerState';
import { MapLayerControls } from '@/features/map/ui/MapLayerControls';
import {
  buildProtectedSatelliteTileUrl,
  fetchSatelliteImageryCatalog,
} from '@/features/map/api/satelliteImageryClient';
import {
  SATELLITE_IMAGERY_SOURCES,
  buildNasaGibsTileUrl,
  observationTimeForSource,
  type SatelliteImagerySource,
  type SatelliteSourceId,
  validObservationTime,
} from '@/features/map/model/satelliteImagery';
import type {
  RegionalPresetId,
  RegionalSelection,
} from '@/features/map/model/regionalPresets';
import type { WeatherAlertsSnapshot } from '@/features/weather/model/weatherAlert';
import type {
  CommonOperationalPicture,
  MapView,
  SelectedEvent,
} from '@/shared/types/assistant';
import {
  createRefreshController,
  REFRESH_POLICIES,
} from '@/shared/model/refreshPolicy';

const DEFAULT_SATELLITE_SOURCE: SatelliteSourceId = 'nasa-viirs-snpp-true-color';
const DEFAULT_SATELLITE_OPACITY = 0.75;
const EMPTY_ACTIVE_INCIDENTS: ActiveIncident[] = [];

export type SatelliteMapState = {
  sourceId: SatelliteSourceId;
  observationTime?: string;
};

type DisasterMapProps = {
  onViewChange: (view: MapView) => void;
  onSelectIncident: (incidentId: string) => void;
  commonOperationalPicture?: CommonOperationalPicture;
  areaOfInterest?: AssistantMapAreaOfInterest;
  activeIncidents?: ActiveIncident[];
  selectedIncidentId?: string;
  selectedEvent?: SelectedEvent;
  layerState?: MapLayerState;
  onLayerStateChange?: (state: MapLayerState) => void;
  correlationCount?: number;
  view?: MapView;
  regionalSelection?: RegionalSelection;
  onRegionalSelectionChange?: (preset: RegionalPresetId) => void;
  satelliteState?: SatelliteMapState;
  onSatelliteStateChange?: (state: SatelliteMapState) => void;
  weatherAlerts?: WeatherAlertsSnapshot;
  focusRequestToken?: number;
};

export function DisasterMap({
  onViewChange,
  onSelectIncident,
  commonOperationalPicture,
  areaOfInterest,
  activeIncidents = EMPTY_ACTIVE_INCIDENTS,
  selectedIncidentId,
  selectedEvent,
  layerState: controlledLayerState,
  onLayerStateChange,
  correlationCount = 0,
  view,
  regionalSelection = 'custom',
  onRegionalSelectionChange,
  satelliteState: controlledSatelliteState,
  onSatelliteStateChange,
  weatherAlerts,
  focusRequestToken = 0,
}: DisasterMapProps) {
  const mapElement = useRef<HTMLDivElement>(null);
  const adapter = useRef<OpenLayersMapAdapter | null>(null);
  const fittedAreaKey = useRef<string | undefined>(undefined);
  const [uncontrolledLayerState, setUncontrolledLayerState] = useState(
    createDefaultMapLayerState,
  );
  const layerState = controlledLayerState ?? uncontrolledLayerState;
  const changeLayerState = onLayerStateChange ?? setUncontrolledLayerState;
  const satelliteEnabled = layerState.visibility['satellite-imagery'];
  const [clusterIncidentIds, setClusterIncidentIds] = useState<string[]>([]);
  const [uncontrolledSatelliteState, setUncontrolledSatelliteState] =
    useState<SatelliteMapState>(() => {
      const source = SATELLITE_IMAGERY_SOURCES.find(
        (item) => item.id === DEFAULT_SATELLITE_SOURCE,
      ) as SatelliteImagerySource;
      return {
        sourceId: source.id,
        observationTime: observationTimeForSource(source),
      };
    });
  const satelliteState = controlledSatelliteState ?? uncontrolledSatelliteState;
  const changeSatelliteState = onSatelliteStateChange ?? setUncontrolledSatelliteState;
  const satelliteSourceId = satelliteState.sourceId;
  const [satelliteOpacity, setSatelliteOpacity] = useState(DEFAULT_SATELLITE_OPACITY);
  const [satelliteSources, setSatelliteSources] = useState(() =>
    SATELLITE_IMAGERY_SOURCES.map((source) => ({ ...source })),
  );
  const [catalogUnavailable, setCatalogUnavailable] = useState(false);
  const loadSatelliteCatalog = useCallback(async (signal: AbortSignal) => {
    try {
      const availability = await fetchSatelliteImageryCatalog(signal);
      if (signal.aborted) return;
      const byId = new Map(availability.map((item) => [item.sourceId, item.available]));
      setSatelliteSources((current) =>
        current.map((source) => ({
          ...source,
          available: byId.get(source.id) ?? source.available,
        })),
      );
      setCatalogUnavailable(false);
    } catch {
      if (signal.aborted) return;
      setCatalogUnavailable(true);
    }
  }, []);
  const incidentFeatures = useMemo(
    () => activeIncidentMapFeatures(activeIncidents),
    [activeIncidents],
  );
  const cycloneLayers = useMemo(() => cycloneMapLayers(selectedEvent), [selectedEvent]);
  const selectedSatelliteSource = useMemo(
    () =>
      satelliteSources.find((source) => source.id === satelliteSourceId) ??
      satelliteSources[0],
    [satelliteSourceId, satelliteSources],
  );
  const requestedObservationTime = satelliteState.observationTime;
  const initialView = useRef(view ?? DEFAULT_MAP_VIEW);
  const satelliteLayerConfiguration = useMemo<
    SatelliteLayerConfiguration | undefined
  >(() => {
    if (
      !satelliteEnabled ||
      !selectedSatelliteSource.available ||
      !validObservationTime(selectedSatelliteSource, requestedObservationTime)
    ) {
      return undefined;
    }
    const url =
      selectedSatelliteSource.access.kind === 'direct-gibs'
        ? buildNasaGibsTileUrl(
            selectedSatelliteSource.id,
            requestedObservationTime as string,
          )
        : buildProtectedSatelliteTileUrl(
            selectedSatelliteSource,
            requestedObservationTime,
          );
    return {
      sourceId: selectedSatelliteSource.id,
      url,
      attribution: selectedSatelliteSource.attribution,
      maximumUsefulZoom: selectedSatelliteSource.maximumUsefulZoom,
      opacity: DEFAULT_SATELLITE_OPACITY,
    };
  }, [satelliteEnabled, requestedObservationTime, selectedSatelliteSource]);

  useEffect(() => {
    const controller = createRefreshController(
      REFRESH_POLICIES['satellite-availability'],
      loadSatelliteCatalog,
      document,
    );
    controller.start();
    return () => controller.stop();
  }, [loadSatelliteCatalog]);

  useEffect(() => {
    if (!mapElement.current) {
      return;
    }
    adapter.current = new OpenLayersMapAdapter({
      target: mapElement.current,
      initialView: initialView.current,
      onViewChange,
      onSelectIncident,
      onSelectIncidentCluster: setClusterIncidentIds,
    });
    return () => {
      adapter.current?.destroy();
      adapter.current = null;
      fittedAreaKey.current = undefined;
    };
  }, [onSelectIncident, onViewChange]);

  useEffect(() => {
    const target = mapElement.current;
    if (!target || typeof ResizeObserver === 'undefined') {
      return;
    }
    const observer = new ResizeObserver(() => adapter.current?.updateSize());
    observer.observe(target);
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    adapter.current?.setCommonOperationalPicture(commonOperationalPicture);
  }, [commonOperationalPicture]);

  useEffect(() => {
    adapter.current?.setCycloneMapLayers(cycloneLayers);
  }, [cycloneLayers]);

  useEffect(() => {
    adapter.current?.setActiveIncidents(incidentFeatures);
  }, [incidentFeatures]);

  useEffect(() => {
    adapter.current?.setWeatherAlerts(weatherAlerts?.alerts ?? []);
  }, [weatherAlerts]);

  useEffect(() => {
    if (view) adapter.current?.setView(view);
  }, [view]);

  useEffect(() => {
    adapter.current?.setLayerVisibility(layerState.visibility);
  }, [layerState.visibility]);

  useEffect(() => {
    adapter.current?.setSelectedIncident(selectedIncidentId);
  }, [focusRequestToken, selectedIncidentId]);

  useEffect(() => {
    adapter.current?.setSatelliteImagery(satelliteLayerConfiguration);
  }, [satelliteLayerConfiguration]);

  useEffect(() => {
    adapter.current?.setSatelliteOpacity(satelliteOpacity);
  }, [satelliteOpacity, satelliteLayerConfiguration]);

  useEffect(() => {
    if (selectedIncidentId) {
      adapter.current?.focusActiveIncident(selectedIncidentId);
    }
  }, [selectedIncidentId]);

  useEffect(() => {
    if (!areaOfInterest || !adapter.current) {
      return;
    }
    const maxZoom = areaOfInterest.maxZoom ?? 10;
    const key = `${areaOfInterest.id}:${areaOfInterest.bounds.join(',')}:${maxZoom}`;
    if (fittedAreaKey.current === key) {
      return;
    }
    adapter.current.fitArea(areaOfInterest.bounds, maxZoom);
    fittedAreaKey.current = key;
  }, [areaOfInterest]);

  const runtimeDetails = {
    'active-incidents': {
      available: true,
      availabilityLabel: `${activeIncidents.length} displayed record${activeIncidents.length === 1 ? '' : 's'}`,
    },
    'satellite-imagery': {
      available: selectedSatelliteSource.available,
      availabilityLabel: selectedSatelliteSource.available
        ? selectedSatelliteSource.provider
        : 'Provider unavailable',
      sourceDetail: `${selectedSatelliteSource.provider}. ${selectedSatelliteSource.attribution}`,
      freshnessDetail: `Requested observation: ${requestedObservationTime ?? 'configured mosaic period'}. Available observation time is not reported by this client.`,
      attribution: selectedSatelliteSource.attribution,
    },
    'authoritative-weather-alerts': {
      available:
        weatherAlerts?.coverage.state === 'alerts_found' ||
        weatherAlerts?.coverage.state === 'no_active_alerts',
      availabilityLabel: weatherAlerts
        ? `${weatherAlerts.alerts.length} active alert${weatherAlerts.alerts.length === 1 ? '' : 's'} · ${weatherAlerts.coverage.state.replaceAll('_', ' ')}`
        : 'Coverage not loaded',
      sourceDetail: weatherAlerts
        ? `${weatherAlerts.coverage.publisher}. ${weatherAlerts.coverage.geographic_scope}`
        : undefined,
      freshnessDetail: weatherAlerts
        ? `Retrieved ${weatherAlerts.retrieved_at}. ${weatherAlerts.coverage.detail}`
        : undefined,
      attribution: weatherAlerts?.coverage.publisher,
    },
    'cop-evidence': {
      available: Boolean(commonOperationalPicture),
      availabilityLabel: commonOperationalPicture
        ? `${commonOperationalPicture.layers.length} retained layer${commonOperationalPicture.layers.length === 1 ? '' : 's'}`
        : 'No current data',
    },
    'cyclone-supplemental': {
      available: cycloneLayers.length > 0,
      availabilityLabel:
        cycloneLayers.length > 0
          ? `${cycloneLayers.length} retained layer${cycloneLayers.length === 1 ? '' : 's'}`
          : 'No current data',
      sourceDetail:
        cycloneLayers.length > 0
          ? [...new Set(cycloneLayers.map((layer) => layer.source.publisher))].join(
              ', ',
            )
          : undefined,
    },
    'compound-correlations': {
      available: correlationCount > 0,
      availabilityLabel:
        correlationCount > 0
          ? `${correlationCount} displayed correlation${correlationCount === 1 ? '' : 's'}`
          : 'No current data',
    },
  } as const;
  const clusteredIncidents = clusterIncidentIds.flatMap((incidentId) => {
    const incident = activeIncidents.find(
      (candidate) => candidate.event_id === incidentId,
    );
    return incident ? [{ incidentId, incident }] : [];
  });
  const weatherAlertContext =
    weatherAlerts && layerState.visibility['authoritative-weather-alerts'] ? (
      <aside className="weather-alerts-legend" aria-label="Weather alert coverage">
        <header>
          <strong>Authoritative weather alerts</strong>
          <span>{weatherAlerts.coverage.state.replaceAll('_', ' ')}</span>
        </header>
        <p>{weatherAlerts.coverage.detail}</p>
        <p>{weatherAlerts.coverage.geographic_scope}</p>
        <p>
          These polygons are official warning areas, not observed disaster event
          footprints. Alerts without source geometry remain listed but are not drawn.
        </p>
        {weatherAlerts.alerts.length > 0 ? (
          <ul>
            {weatherAlerts.alerts.slice(0, 8).map((alert) => (
              <li key={alert.provider_alert_id}>
                <strong>{alert.event}</strong>
                <span>{alert.affected_area}</span>
                <small>
                  {alert.severity} severity · {alert.urgency} urgency ·{' '}
                  {alert.certainty} certainty
                </small>
                <small>
                  Effective {alert.effective ?? 'not reported'} · expires{' '}
                  {alert.expires ?? 'not reported'}
                </small>
                <small>
                  {alert.geometry
                    ? 'Source polygon displayed'
                    : 'No source polygon supplied'}
                </small>
                {alert.canonical_url ? (
                  <a href={alert.canonical_url} target="_blank" rel="noreferrer">
                    Open source alert
                  </a>
                ) : null}
              </li>
            ))}
          </ul>
        ) : null}
        {weatherAlerts.alerts.length > 8 ? (
          <small>
            {weatherAlerts.alerts.length - 8} additional active alerts omitted from this
            compact list.
          </small>
        ) : null}
        {weatherAlerts.warnings.map((warning) => (
          <p key={`${warning.reason_code}:${warning.detail}`}>{warning.detail}</p>
        ))}
      </aside>
    ) : null;

  return (
    <>
      <div className="map-canvas" ref={mapElement} aria-label="Interactive map" />
      <MapLayerControls
        state={layerState}
        onChange={changeLayerState}
        runtimeDetails={runtimeDetails}
        regionalSelection={regionalSelection}
        onRegionalSelectionChange={onRegionalSelectionChange}
        supplemental={weatherAlertContext}
      >
        <fieldset className="satellite-controls">
          <legend>Satellite imagery source</legend>
          <div className="satellite-controls-heading">
            <strong>{selectedSatelliteSource.provider}</strong>
            <span>{satelliteEnabled ? 'Layer on' : 'Layer off'}</span>
          </div>
          <label>
            <span>Satellite source</span>
            <select
              value={satelliteSourceId}
              onChange={(event) => {
                const sourceId = event.target.value as SatelliteSourceId;
                const source = satelliteSources.find((item) => item.id === sourceId);
                if (!source) return;
                changeSatelliteState({
                  sourceId,
                  observationTime: observationTimeForSource(source),
                });
              }}
            >
              {satelliteSources.map((source) => (
                <option key={source.id} value={source.id} disabled={!source.available}>
                  {source.displayName}
                </option>
              ))}
            </select>
          </label>
          <label>
            <span>Satellite opacity</span>
            <input
              type="range"
              min="0"
              max="1"
              step="0.05"
              value={satelliteOpacity}
              disabled={!satelliteEnabled}
              onChange={(event) => setSatelliteOpacity(Number(event.target.value))}
            />
            <output>{Math.round(satelliteOpacity * 100)}%</output>
          </label>
          {selectedSatelliteSource.temporalMode === 'daily' ? (
            <label>
              <span>Observation date</span>
              <input
                type="date"
                value={requestedObservationTime ?? ''}
                disabled={!satelliteEnabled}
                onChange={(event) =>
                  changeSatelliteState({
                    sourceId: satelliteSourceId,
                    observationTime: event.target.value,
                  })
                }
              />
            </label>
          ) : selectedSatelliteSource.temporalMode === 'subdaily' ? (
            <label>
              <span>Observation date/time (UTC)</span>
              <input
                type="datetime-local"
                step="600"
                value={requestedObservationTime?.slice(0, 16) ?? ''}
                disabled={!satelliteEnabled}
                onChange={(event) =>
                  changeSatelliteState({
                    sourceId: satelliteSourceId,
                    observationTime: event.target.value
                      ? `${event.target.value}:00Z`
                      : undefined,
                  })
                }
              />
            </label>
          ) : (
            <span className="satellite-fixed-time">
              Observation time: configured mosaic period
            </span>
          )}
          <div className="satellite-source-details" aria-live="polite">
            <span>Provider: {selectedSatelliteSource.provider}</span>
            <span>
              Requested observation:{' '}
              {requestedObservationTime ?? 'configured mosaic period'}
            </span>
            <span>
              Available observation time is not reported by this client; the requested
              time may be unavailable.
            </span>
            <span>Attribution: {selectedSatelliteSource.attribution}</span>
            <strong>Imagery is not live.</strong>
            {!selectedSatelliteSource.available ? (
              <strong>Provider unavailable: server configuration is required.</strong>
            ) : null}
            {catalogUnavailable ? (
              <strong>
                Provider catalog unavailable; credentialed providers remain disabled.
              </strong>
            ) : null}
          </div>
        </fieldset>
      </MapLayerControls>
      {clusteredIncidents.length > 0 ? (
        <aside className="incident-cluster-picker" aria-label="Clustered incidents">
          <header>
            <strong>{clusteredIncidents.length} incidents at this map scale</strong>
            <button type="button" onClick={() => setClusterIncidentIds([])}>
              Close
            </button>
          </header>
          <p>Select an underlying source record.</p>
          <ul>
            {clusteredIncidents.map(({ incidentId, incident }) => {
              return (
                <li key={incidentId}>
                  <button
                    type="button"
                    onClick={() => {
                      setClusterIncidentIds([]);
                      onSelectIncident(incidentId);
                    }}
                  >
                    {incident.location}
                  </button>
                </li>
              );
            })}
          </ul>
        </aside>
      ) : null}
      {commonOperationalPicture && layerState.visibility['cop-evidence'] && (
        <aside className="cop-legend" aria-label="Common operational picture legend">
          <strong>Common operational picture</strong>
          <span>Status: {commonOperationalPicture.status}</span>
          <ul>
            {commonOperationalPicture.layers.flatMap((layer) =>
              layer.features.map((feature) => {
                const semantics = copStyleSemantics(feature.authority);
                return (
                  <li key={feature.feature_id}>
                    <span
                      className={`legend-line legend-line-${semantics.patternLabel}`}
                      aria-hidden="true"
                    />
                    <span>
                      <b>{semantics.authorityLabel}</b> · {layer.title}
                      <small>
                        Layer: {layer.status} · {layer.uncertainty}
                      </small>
                      <small>
                        Feature: {feature.status} · {feature.uncertainty}
                      </small>
                      <small>Attribution: {feature.attribution}</small>
                    </span>
                  </li>
                );
              }),
            )}
          </ul>
        </aside>
      )}
      {cycloneLayers.length > 0 && layerState.visibility['cyclone-supplemental'] && (
        <aside className="cyclone-legend" aria-label="Cyclone forecast layers">
          <strong>Cyclone layers</strong>
          <ul>
            {cycloneLayers.map((layer) => {
              const semantics = cycloneStyleSemantics(layer.semantic_role);
              const label =
                layer.semantic_role === 'wind_radii' && layer.wind_threshold
                  ? `${semantics.label} · ${layer.wind_threshold} ${layer.wind_threshold_unit}`
                  : semantics.label;
              return (
                <li key={layer.layer_id}>
                  <span
                    className={`cyclone-legend-mark cyclone-legend-${layer.semantic_role}`}
                    aria-hidden="true"
                  />
                  <span>
                    <b>{label}</b>
                    <small>{layer.source.publisher}</small>
                    <small>{layer.limitation}</small>
                  </span>
                </li>
              );
            })}
          </ul>
          <p>Forecast and uncertainty geometry are not observed storm footprints.</p>
        </aside>
      )}
    </>
  );
}
