'use client';

import { useEffect, useRef, useState } from 'react';

import Feature from 'ol/Feature';
import GeoJSON from 'ol/format/GeoJSON';
import Map from 'ol/Map';
import View from 'ol/View';
import VectorLayer from 'ol/layer/Vector';
import TileLayer from 'ol/layer/Tile';
import VectorSource from 'ol/source/Vector';
import XYZ from 'ol/source/XYZ';
import OSM from 'ol/source/OSM';
import Fill from 'ol/style/Fill';
import Stroke from 'ol/style/Stroke';
import Style from 'ol/style/Style';
import ScaleLine from 'ol/control/ScaleLine';

import type {
  GroundImageryArtifactResponse,
  GroundImageryObservationResponse,
  GroundImageryRegionResponse,
} from '@/shared/api/generated/assistant';
import { API_BASE_URL } from '@/shared/config/runtime';

type GroundCoverageMapProps = {
  artifact: GroundImageryArtifactResponse;
  observation: GroundImageryObservationResponse;
  region: GroundImageryRegionResponse | null;
};

const geometryReader = new GeoJSON();

function overlay(
  geometry: Record<string, unknown>,
  color: string,
  fill: string,
  dash?: number[],
): VectorLayer<VectorSource<Feature>> | undefined {
  if (!Array.isArray(geometry.coordinates) || geometry.coordinates.length === 0)
    return undefined;
  try {
    const feature = new Feature({
      geometry: geometryReader.readGeometry(geometry, {
        dataProjection: 'EPSG:4326',
        featureProjection: 'EPSG:3857',
      }),
    });
    return new VectorLayer({
      source: new VectorSource({ features: [feature] }),
      style: new Style({
        fill: new Fill({ color: fill }),
        stroke: new Stroke({ color, width: 2, lineDash: dash }),
      }),
    });
  } catch {
    return undefined;
  }
}

export function GroundCoverageMap({
  artifact,
  observation,
  region,
}: GroundCoverageMapProps) {
  const target = useRef<HTMLDivElement>(null);
  const imageLayer = useRef<TileLayer<XYZ> | null>(null);
  const [opacity, setOpacity] = useState(85);

  useEffect(() => {
    if (!target.current || !region) return;
    const inspection = overlay(
      region.inspection,
      '#f8c45a',
      'rgba(248, 196, 90, 0.06)',
      [7, 5],
    );
    if (!inspection) return;
    const core = overlay(region.core, '#fefefe', 'rgba(255, 255, 255, 0.06)');
    const footprint = overlay(
      observation.footprint,
      '#55d9cd',
      'rgba(85, 217, 205, 0.03)',
      [3, 4],
    );
    const image = new TileLayer({
      opacity: 0.85,
      source: new XYZ({
        url: `${API_BASE_URL}/ground-imagery/artifacts/${encodeURIComponent(artifact.artifact_id)}/tiles/{z}/{x}/{y}.png`,
        crossOrigin: 'anonymous',
      }),
    });
    imageLayer.current = image;
    const layers = [
      new TileLayer({ source: new OSM() }),
      image,
      footprint,
      inspection,
      core,
    ].filter((layer) => layer !== undefined);
    const map = new Map({
      target: target.current,
      layers,
      view: new View({ center: [0, 0], zoom: 2 }),
    });
    map.addControl(new ScaleLine());
    const extent = inspection.getSource()?.getExtent();
    if (extent) map.getView().fit(extent, { padding: [24, 24, 24, 24], maxZoom: 13 });
    map.updateSize();
    return () => {
      map.setTarget(undefined);
      imageLayer.current = null;
    };
  }, [artifact.artifact_id, observation.footprint, region]);

  useEffect(() => imageLayer.current?.setOpacity(opacity / 100), [opacity]);

  return (
    <section className="ground-coverage-map" aria-label="Observation coverage map">
      <div ref={target} className="ground-coverage-map-canvas" />
      <label className="ground-coverage-opacity">
        Image opacity {opacity}%
        <input
          type="range"
          min="0"
          max="100"
          step="5"
          value={opacity}
          onChange={(event) => setOpacity(Number(event.target.value))}
        />
      </label>
      <p>
        <span className="ground-map-key is-core" /> Incident core ·{' '}
        <span className="ground-map-key is-inspection" /> Inspection region ·{' '}
        <span className="ground-map-key is-footprint" /> Acquisition footprint ·
        OpenStreetMap base
      </p>
      <p>
        Transparent pixels have no data from this capture. Visible pixels can still be
        obscured or uncertain; consult the regional quality state before interpreting
        them.
      </p>
    </section>
  );
}
