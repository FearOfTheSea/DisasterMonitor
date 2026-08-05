'use client';

import { useEffect, useRef } from 'react';
import 'ol/ol.css';

import { OpenLayersMapAdapter } from '@/features/map/adapters/openLayersMapAdapter';
import { DEFAULT_MAP_VIEW } from '@/features/map/model/mapView';
import type { MapView } from '@/shared/types/assistant';

type DisasterMapProps = {
  onViewChange: (view: MapView) => void;
};

export function DisasterMap({ onViewChange }: DisasterMapProps) {
  const mapElement = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!mapElement.current) {
      return;
    }
    const adapter = new OpenLayersMapAdapter({
      target: mapElement.current,
      initialView: DEFAULT_MAP_VIEW,
      onViewChange,
    });
    return () => adapter.destroy();
  }, [onViewChange]);

  return <div className="map-canvas" ref={mapElement} aria-label="Interactive map" />;
}
