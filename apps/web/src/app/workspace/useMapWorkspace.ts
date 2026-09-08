'use client';

import { useCallback, useMemo, useState } from 'react';

import type { IncidentMapRecord } from '@/features/incidents/model/activeIncidents';
import {
  createDefaultMapLayerState,
  setMapLayerVisibility,
} from '@/features/map/model/mapLayerState';
import { type MapUrlState } from '@/features/map/model/mapUrlState';
import {
  applyRegionalPreset,
  regionalPresetAfterViewChange,
  type RegionalPresetId,
  type RegionalSelection,
} from '@/features/map/model/regionalPresets';
import {
  observationTimeForSource,
  SATELLITE_IMAGERY_SOURCES,
  type SatelliteMapState,
} from '@/features/map/model/satelliteImagery';
import { DEFAULT_MAP_VIEW } from '@/shared/config/runtime';
import type { MapView } from '@/shared/types/assistant';

import type { ActiveIncidentsStatus } from '@/features/incidents/hooks/useActiveIncidents';
import type { ActiveIncidentsSnapshot } from '@/features/incidents/model/activeIncidents';
import { useWorkspaceUrlState } from './useWorkspaceUrlState';

export function useMapWorkspace(activeIncidents: {
  status: ActiveIncidentsStatus;
  snapshot?: ActiveIncidentsSnapshot;
}) {
  const [selectedIncidentId, setSelectedIncidentId] = useState<string>();
  const [watchFocusIncident, setWatchFocusIncident] = useState<IncidentMapRecord>();
  const [mapLayerState, setMapLayerState] = useState(createDefaultMapLayerState);
  const [mapView, setMapView] = useState<MapView>(DEFAULT_MAP_VIEW);
  const [regionalSelection, setRegionalSelection] =
    useState<RegionalSelection>('custom');
  const [satelliteState, setSatelliteState] = useState<SatelliteMapState>(() => {
    const source = SATELLITE_IMAGERY_SOURCES[0];
    return {
      sourceId: source.id,
      observationTime: observationTimeForSource(source),
    };
  });
  const [focusRequestToken, setFocusRequestToken] = useState(0);
  const [defaultUrlState] = useState<MapUrlState>(() => {
    return {
      view: DEFAULT_MAP_VIEW,
      regionalPreset: 'custom',
      selectedIncidentId: undefined,
      layerState: createDefaultMapLayerState(),
      satelliteSourceId: satelliteState.sourceId,
      satelliteObservationTime: satelliteState.observationTime,
    };
  });
  const usableSelectedIncidentId =
    activeIncidents.status === 'success' &&
    selectedIncidentId &&
    !watchFocusIncident &&
    !activeIncidents.snapshot?.incidents.some(
      (incident) => incident.event_id === selectedIncidentId,
    )
      ? undefined
      : selectedIncidentId;
  const handleViewChange = useCallback((view: MapView) => {
    setMapView(view);
    setRegionalSelection((current) => regionalPresetAfterViewChange(current, view));
  }, []);
  const handleSelectRegion = useCallback((region: RegionalPresetId) => {
    const next = applyRegionalPreset(region);
    setRegionalSelection(next.regionalPreset);
    setMapView(next.view);
  }, []);
  const handleSelectActiveIncident = useCallback((incidentId: string) => {
    setWatchFocusIncident(undefined);
    setSelectedIncidentId(incidentId);
    setFocusRequestToken((current) => current + 1);
    setMapLayerState((current) =>
      setMapLayerVisibility(current, 'active-incidents', true),
    );
  }, []);
  const handleSelectWatchIncident = useCallback((incident: IncidentMapRecord) => {
    setWatchFocusIncident(incident);
    setSelectedIncidentId(incident.event_id);
    setFocusRequestToken((current) => current + 1);
    setMapLayerState((current) =>
      setMapLayerVisibility(current, 'active-incidents', true),
    );
  }, []);
  const restoreUrlState = useCallback((restored: MapUrlState) => {
    setMapView(restored.view);
    setRegionalSelection(restored.regionalPreset);
    setSelectedIncidentId(restored.selectedIncidentId);
    setWatchFocusIncident(undefined);
    setMapLayerState(restored.layerState);
    setSatelliteState({
      sourceId: restored.satelliteSourceId,
      observationTime: restored.satelliteObservationTime,
    });
  }, []);
  const urlState = useMemo(
    () => ({
      view: mapView,
      regionalPreset: regionalSelection,
      selectedIncidentId: usableSelectedIncidentId,
      layerState: mapLayerState,
      satelliteSourceId: satelliteState.sourceId,
      satelliteObservationTime: satelliteState.observationTime,
    }),
    [
      mapView,
      regionalSelection,
      usableSelectedIncidentId,
      mapLayerState,
      satelliteState,
    ],
  );
  useWorkspaceUrlState(defaultUrlState, urlState, restoreUrlState);
  return {
    mapView,
    mapLayerState,
    setMapLayerState,
    regionalSelection,
    satelliteState,
    setSatelliteState,
    focusRequestToken,
    setFocusRequestToken,
    watchFocusIncident,
    usableSelectedIncidentId,
    handleViewChange,
    handleSelectRegion,
    handleSelectActiveIncident,
    handleSelectWatchIncident,
  };
}
