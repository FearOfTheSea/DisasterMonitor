'use client';

import { useEffect, useMemo, useRef } from 'react';
import 'ol/ol.css';

import { OpenLayersMapAdapter } from '@/features/map/adapters/openLayersMapAdapter';
import type { ActiveIncident } from '@/features/incidents/model/activeIncidents';
import type { AssistantMapAreaOfInterest } from '@/features/map/model/assistantMapFocus';
import { activeIncidentMapFeatures } from '@/features/map/model/activeIncidentMap';
import { copStyleSemantics } from '@/features/map/model/copRenderPlan';
import { DEFAULT_MAP_VIEW } from '@/features/map/model/mapView';
import type { CommonOperationalPicture, MapView } from '@/shared/types/assistant';

type DisasterMapProps = {
  onViewChange: (view: MapView) => void;
  commonOperationalPicture?: CommonOperationalPicture;
  areaOfInterest?: AssistantMapAreaOfInterest;
  activeIncidents?: ActiveIncident[];
  selectedIncidentId?: string;
};

export function DisasterMap({
  onViewChange,
  commonOperationalPicture,
  areaOfInterest,
  activeIncidents = [],
  selectedIncidentId,
}: DisasterMapProps) {
  const mapElement = useRef<HTMLDivElement>(null);
  const adapter = useRef<OpenLayersMapAdapter | null>(null);
  const fittedAreaKey = useRef<string | undefined>(undefined);
  const incidentFeatures = useMemo(
    () => activeIncidentMapFeatures(activeIncidents),
    [activeIncidents],
  );

  useEffect(() => {
    if (!mapElement.current) {
      return;
    }
    adapter.current = new OpenLayersMapAdapter({
      target: mapElement.current,
      initialView: DEFAULT_MAP_VIEW,
      onViewChange,
    });
    return () => {
      adapter.current?.destroy();
      adapter.current = null;
      fittedAreaKey.current = undefined;
    };
  }, [onViewChange]);

  useEffect(() => {
    adapter.current?.setCommonOperationalPicture(commonOperationalPicture);
  }, [commonOperationalPicture]);

  useEffect(() => {
    adapter.current?.setActiveIncidents(incidentFeatures);
  }, [incidentFeatures]);

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
