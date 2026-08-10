'use client';

import { useEffect, useRef } from 'react';
import 'ol/ol.css';

import { OpenLayersMapAdapter } from '@/features/map/adapters/openLayersMapAdapter';
import { copStyleSemantics } from '@/features/map/model/copRenderPlan';
import { DEFAULT_MAP_VIEW } from '@/features/map/model/mapView';
import type { CommonOperationalPicture, MapView } from '@/shared/types/assistant';

type DisasterMapProps = {
  onViewChange: (view: MapView) => void;
  commonOperationalPicture?: CommonOperationalPicture;
};

export function DisasterMap({
  onViewChange,
  commonOperationalPicture,
}: DisasterMapProps) {
  const mapElement = useRef<HTMLDivElement>(null);
  const adapter = useRef<OpenLayersMapAdapter | null>(null);

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
    };
  }, [onViewChange]);

  useEffect(() => {
    adapter.current?.setCommonOperationalPicture(commonOperationalPicture);
  }, [commonOperationalPicture]);

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
