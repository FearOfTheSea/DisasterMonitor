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
import { DEFAULT_MAP_VIEW } from '@/features/map/model/mapView';
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
import type { CommonOperationalPicture, MapView } from '@/shared/types/assistant';

const DEFAULT_SATELLITE_SOURCE: SatelliteSourceId = 'nasa-viirs-snpp-true-color';
const DEFAULT_SATELLITE_OPACITY = 0.75;

type DisasterMapProps = {
  onViewChange: (view: MapView) => void;
  onSelectIncident: (incidentId: string) => void;
  commonOperationalPicture?: CommonOperationalPicture;
  areaOfInterest?: AssistantMapAreaOfInterest;
  activeIncidents?: ActiveIncident[];
  selectedIncidentId?: string;
};

export function DisasterMap({
  onViewChange,
  onSelectIncident,
  commonOperationalPicture,
  areaOfInterest,
  activeIncidents = [],
  selectedIncidentId,
}: DisasterMapProps) {
  const mapElement = useRef<HTMLDivElement>(null);
  const adapter = useRef<OpenLayersMapAdapter | null>(null);
  const fittedAreaKey = useRef<string | undefined>(undefined);
  const [satelliteEnabled, setSatelliteEnabled] = useState(false);
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
    adapter.current?.setActiveIncidents(incidentFeatures);
  }, [incidentFeatures]);

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

  return (
    <>
      <div className="map-canvas" ref={mapElement} aria-label="Interactive map" />
      <fieldset className="satellite-controls">
        <legend>Satellite</legend>
        <div className="satellite-controls-heading">
          <label className="satellite-toggle">
            <input
              type="checkbox"
              checked={satelliteEnabled}
              onChange={(event) => setSatelliteEnabled(event.target.checked)}
            />
            <span>Satellite imagery</span>
          </label>
          <span>{satelliteEnabled ? 'On' : 'Off'}</span>
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
      {commonOperationalPicture && (
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
    </>
  );
}
