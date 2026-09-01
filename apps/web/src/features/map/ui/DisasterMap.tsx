'use client';

import { useEffect, useMemo, useRef, useState } from 'react';
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
  CommonOperationalPicture,
  MapView,
  SelectedEvent,
} from '@/shared/types/assistant';

const DEFAULT_SATELLITE_SOURCE: SatelliteSourceId = 'nasa-viirs-snpp-true-color';
const DEFAULT_SATELLITE_OPACITY = 0.75;
const EMPTY_ACTIVE_INCIDENTS: ActiveIncident[] = [];

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
  const [satelliteSourceId, setSatelliteSourceId] = useState<SatelliteSourceId>(
    DEFAULT_SATELLITE_SOURCE,
  );
  const [satelliteOpacity, setSatelliteOpacity] = useState(DEFAULT_SATELLITE_OPACITY);
  const [dailyObservationDate, setDailyObservationDate] = useState(() =>
    new Date().toISOString().slice(0, 10),
  );
  const [subdailyObservationTime, setSubdailyObservationTime] = useState(() => {
    const source = SATELLITE_IMAGERY_SOURCES.find(
      (item) => item.id === 'nasa-goes-east-geocolor',
    ) as SatelliteImagerySource;
    return observationTimeForSource(source)?.slice(0, 16) ?? '';
  });
  const [satelliteSources, setSatelliteSources] = useState(() =>
    SATELLITE_IMAGERY_SOURCES.map((source) => ({ ...source })),
  );
  const [catalogUnavailable, setCatalogUnavailable] = useState(false);
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
  const requestedObservationTime =
    selectedSatelliteSource.temporalMode === 'daily'
      ? dailyObservationDate
      : selectedSatelliteSource.temporalMode === 'subdaily'
        ? `${subdailyObservationTime}:00Z`
        : undefined;
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
    const controller = new AbortController();
    fetchSatelliteImageryCatalog(controller.signal)
      .then((availability) => {
        const byId = new Map(
          availability.map((item) => [item.sourceId, item.available]),
        );
        setSatelliteSources((current) =>
          current.map((source) => ({
            ...source,
            available: byId.get(source.id) ?? source.available,
          })),
        );
        setCatalogUnavailable(false);
      })
      .catch((error: unknown) => {
        if (error instanceof DOMException && error.name === 'AbortError') return;
        setCatalogUnavailable(true);
      });
    return () => controller.abort();
  }, []);

  useEffect(() => {
    if (!mapElement.current) {
      return;
    }
    adapter.current = new OpenLayersMapAdapter({
      target: mapElement.current,
      initialView: DEFAULT_MAP_VIEW,
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
    adapter.current?.setLayerVisibility(layerState.visibility);
  }, [layerState.visibility]);

  useEffect(() => {
    adapter.current?.setSelectedIncident(selectedIncidentId);
  }, [selectedIncidentId]);

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

  return (
    <>
      <div className="map-canvas" ref={mapElement} aria-label="Interactive map" />
      <MapLayerControls
        state={layerState}
        onChange={changeLayerState}
        runtimeDetails={runtimeDetails}
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
              onChange={(event) =>
                setSatelliteSourceId(event.target.value as SatelliteSourceId)
              }
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
                value={dailyObservationDate}
                disabled={!satelliteEnabled}
                onChange={(event) => setDailyObservationDate(event.target.value)}
              />
            </label>
          ) : selectedSatelliteSource.temporalMode === 'subdaily' ? (
            <label>
              <span>Observation date/time (UTC)</span>
              <input
                type="datetime-local"
                step="600"
                value={subdailyObservationTime}
                disabled={!satelliteEnabled}
                onChange={(event) => setSubdailyObservationTime(event.target.value)}
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
