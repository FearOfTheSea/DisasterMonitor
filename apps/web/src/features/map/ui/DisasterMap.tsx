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
import { cycloneMapLayers } from '@/features/map/model/cycloneMapLayers';
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
  type SatelliteMapState,
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
import {
  CommonOperationalPictureLegend,
  CycloneLegend,
  IncidentClusterPicker,
  SatelliteImageryControls,
  WeatherAlertCoverage,
} from '@/features/map/ui/DisasterMapPanels';

const DEFAULT_SATELLITE_SOURCE: SatelliteSourceId = 'nasa-viirs-snpp-true-color';
const DEFAULT_SATELLITE_OPACITY = 0.75;
const EMPTY_ACTIVE_INCIDENTS: ActiveIncident[] = [];

function sameMapView(first: MapView, second: MapView): boolean {
  return (
    Math.abs(first.centerLatitude - second.centerLatitude) < 0.0001 &&
    Math.abs(first.centerLongitude - second.centerLongitude) < 0.0001 &&
    Math.abs(first.zoom - second.zoom) < 0.01
  );
}

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
  const lastReportedView = useRef(view ?? DEFAULT_MAP_VIEW);
  const handleViewChange = useCallback(
    (nextView: MapView) => {
      lastReportedView.current = nextView;
      onViewChange(nextView);
    },
    [onViewChange],
  );
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
      onViewChange: handleViewChange,
      onSelectIncident,
      onSelectIncidentCluster: setClusterIncidentIds,
    });
    return () => {
      adapter.current?.destroy();
      adapter.current = null;
      fittedAreaKey.current = undefined;
    };
  }, [handleViewChange, onSelectIncident]);

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
    if (!view || sameMapView(view, lastReportedView.current)) {
      return;
    }
    adapter.current?.setView(view);
    lastReportedView.current = view;
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

  const runtimeDetails = useMemo(
    () =>
      ({
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
      }) as const,
    [
      activeIncidents.length,
      commonOperationalPicture,
      correlationCount,
      cycloneLayers,
      requestedObservationTime,
      selectedSatelliteSource,
      weatherAlerts,
    ],
  );
  const clusteredIncidents = useMemo(() => {
    const incidentsById = new Map(
      activeIncidents.map((incident) => [incident.event_id, incident]),
    );
    return clusterIncidentIds.flatMap((incidentId) => {
      const incident = incidentsById.get(incidentId);
      return incident ? [{ incidentId, incident }] : [];
    });
  }, [activeIncidents, clusterIncidentIds]);
  const weatherAlertContext =
    weatherAlerts && layerState.visibility['authoritative-weather-alerts'] ? (
      <WeatherAlertCoverage snapshot={weatherAlerts} />
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
        <SatelliteImageryControls
          enabled={satelliteEnabled}
          source={selectedSatelliteSource}
          sources={satelliteSources}
          state={satelliteState}
          opacity={satelliteOpacity}
          catalogUnavailable={catalogUnavailable}
          onStateChange={changeSatelliteState}
          onOpacityChange={setSatelliteOpacity}
        />
      </MapLayerControls>
      <IncidentClusterPicker
        incidents={clusteredIncidents}
        onClose={() => setClusterIncidentIds([])}
        onSelectIncident={(incidentId) => {
          setClusterIncidentIds([]);
          onSelectIncident(incidentId);
        }}
      />
      <CommonOperationalPictureLegend
        picture={commonOperationalPicture}
        visible={layerState.visibility['cop-evidence']}
      />
      <CycloneLegend
        layers={cycloneLayers}
        visible={layerState.visibility['cyclone-supplemental']}
      />
    </>
  );
}
