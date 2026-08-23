import Feature from 'ol/Feature';
import Map from 'ol/Map';
import View from 'ol/View';
import TileLayer from 'ol/layer/Tile';
import VectorLayer from 'ol/layer/Vector';
import Geometry from 'ol/geom/Geometry';
import LineString from 'ol/geom/LineString';
import Point from 'ol/geom/Point';
import Polygon from 'ol/geom/Polygon';
import OSM from 'ol/source/OSM';
import VectorSource from 'ol/source/Vector';
import XYZ from 'ol/source/XYZ';
import { fromLonLat, toLonLat } from 'ol/proj';
import { Circle as CircleStyle, Fill, Stroke, Style } from 'ol/style';

import {
  buildCopRenderPlan,
  copStyleSemantics,
  type CopAuthority,
} from '@/features/map/model/copRenderPlan';
import type {
  ActiveIncidentMapFeature,
  RenderableIncidentGeometry,
} from '@/features/map/model/activeIncidentMap';
import type { DisasterType } from '@/features/incidents/model/activeIncidents';
import type { MapAreaBounds } from '@/features/map/model/assistantMapFocus';
import type {
  CommonOperationalPicture,
  CopGeometry,
  MapView,
} from '@/shared/types/assistant';

type MapAdapterOptions = {
  target: HTMLElement;
  initialView: MapView;
  onViewChange: (view: MapView) => void;
  onSelectIncident: (incidentId: string) => void;
};

export type SatelliteLayerConfiguration = {
  sourceId: string;
  url: string;
  attribution: string;
  maximumUsefulZoom: number;
  opacity: number;
};

const DEFAULT_FIT_PADDING = 56;
const WEB_MERCATOR_MAX_LATITUDE = 85.0511287798066;

type PendingArea = {
  bounds: MapAreaBounds;
  maxZoom: number;
};

export class OpenLayersMapAdapter {
  private readonly map: Map;
  private readonly activeIncidentSource: VectorSource<Feature<Geometry>>;
  private readonly activeIncidentLayer: VectorLayer<VectorSource<Feature<Geometry>>>;
  private satelliteLayer?: TileLayer<XYZ>;
  private copLayers: VectorLayer<VectorSource<Feature<Geometry>>>[] = [];
  private pendingArea?: PendingArea;
  private pendingIncidentId?: string;

  constructor(private readonly options: MapAdapterOptions) {
    const baseLayer = new TileLayer({ source: new OSM() });
    baseLayer.set('dmLayerType', 'base');
    baseLayer.setZIndex(0);
    const view = new View({
      center: fromLonLat([
        options.initialView.centerLongitude,
        options.initialView.centerLatitude,
      ]),
      zoom: options.initialView.zoom,
      minZoom: 2,
      maxZoom: 18,
      projection: 'EPSG:3857',
      constrainResolution: true,
    });
    this.activeIncidentSource = new VectorSource<Feature<Geometry>>();
    this.activeIncidentLayer = new VectorLayer({
      source: this.activeIncidentSource,
      style: (feature) =>
        styleForActiveIncident(
          feature.get('disaster'),
          feature.get('selected') === true,
        ),
    });
    this.activeIncidentLayer.set('dmLayerType', 'active-incidents');
    this.activeIncidentLayer.setZIndex(10);
    this.map = new Map({
      target: options.target,
      layers: [baseLayer, this.activeIncidentLayer],
      view,
    });
    this.map.on('singleclick', (event) => {
      const feature = this.map.forEachFeatureAtPixel(
        event.pixel,
        (candidate) => candidate,
        { layerFilter: (layer) => layer === this.activeIncidentLayer },
      );
      const incidentId = feature?.get('incidentId');
      if (typeof incidentId === 'string') {
        options.onSelectIncident(incidentId);
      }
    });
    this.map.on('change:size', () => {
      this.applyPendingIncidentFocus();
      this.applyPendingArea();
    });
    view.on('change:center', () => this.reportView());
    view.on('change:resolution', () => this.reportView());
  }

  destroy(): void {
    this.pendingArea = undefined;
    this.pendingIncidentId = undefined;
    this.activeIncidentSource.clear();
    this.clearSatelliteImagery();
    this.clearCommonOperationalPicture();
    this.map.setTarget(undefined);
  }

  updateSize(): void {
    this.map.updateSize();
  }

  setCommonOperationalPicture(cop?: CommonOperationalPicture): void {
    this.clearCommonOperationalPicture();
    if (!cop) return;

    const renderPlan = buildCopRenderPlan(cop);
    for (const copLayer of cop.layers) {
      const features = renderPlan.filter((item) => item.layerId === copLayer.layer_id);
      const source = new VectorSource<Feature<Geometry>>({
        features: features.map(
          (item) =>
            new Feature({
              geometry: toOpenLayersGeometry(item.geometry),
              featureId: item.featureId,
              authority: item.authority,
              semanticKind: item.semanticKind,
              status: item.status,
              uncertainty: item.uncertainty,
              attribution: item.attribution,
            }),
        ),
      });
      const layer = new VectorLayer({
        source,
        style: (feature) => styleForAuthority(feature.get('authority')),
      });
      layer.set('dmCopId', cop.cop_id);
      layer.set('dmLayerType', 'common-operational-picture');
      layer.setZIndex(20);
      this.map.addLayer(layer);
      this.copLayers.push(layer);
    }
  }

  setSatelliteImagery(configuration?: SatelliteLayerConfiguration): void {
    this.clearSatelliteImagery();
    if (!configuration) return;
    const layer = new TileLayer({
      opacity: validOpacity(configuration.opacity) ? configuration.opacity : 1,
      source: new XYZ({
        url: configuration.url,
        attributions: configuration.attribution,
        maxZoom: configuration.maximumUsefulZoom,
        crossOrigin: 'anonymous',
      }),
    });
    layer.set('dmLayerType', 'satellite-imagery');
    layer.set('dmSatelliteSourceId', configuration.sourceId);
    layer.setZIndex(1);
    this.map.getLayers().insertAt(1, layer);
    this.satelliteLayer = layer;
  }

  setSatelliteOpacity(opacity: number): void {
    if (this.satelliteLayer && validOpacity(opacity)) {
      this.satelliteLayer.setOpacity(opacity);
    }
  }

  setActiveIncidents(incidents: readonly ActiveIncidentMapFeature[]): void {
    this.activeIncidentSource.clear();
    this.activeIncidentSource.addFeatures(
      incidents.map(
        (incident) =>
          new Feature({
            geometry: toActiveIncidentGeometry(incident.geometry),
            incidentId: incident.incidentId,
            disaster: incident.disaster,
          }),
      ),
    );
    this.applyPendingIncidentFocus();
  }

  setSelectedIncident(incidentId?: string): void {
    for (const feature of this.activeIncidentSource.getFeatures()) {
      feature.set('selected', feature.get('incidentId') === incidentId);
    }
  }

  focusActiveIncident(incidentId: string): void {
    this.pendingIncidentId = incidentId;
    this.map.updateSize();
    this.applyPendingIncidentFocus();
  }

  fitArea(bounds: MapAreaBounds, maxZoom = 10): void {
    if (!validAreaBounds(bounds) || !validMaxZoom(maxZoom)) {
      return;
    }
    this.pendingArea = { bounds: [...bounds], maxZoom };
    this.map.updateSize();
    this.applyPendingArea();
  }

  private applyPendingArea(): void {
    if (!this.pendingArea) {
      return;
    }
    const size = this.map.getSize();
    if (!size || size[0] <= 0 || size[1] <= 0) {
      return;
    }
    const extent = projectedExtent(this.pendingArea.bounds);
    if (!extent) {
      this.pendingArea = undefined;
      return;
    }
    const { maxZoom } = this.pendingArea;
    this.pendingArea = undefined;
    const view = this.map.getView();
    view.cancelAnimations();
    this.map.getView().fit(extent, {
      duration: reducedMotionPreferred() ? 0 : 400,
      padding: fitPadding(size),
      maxZoom,
      size,
    });
  }

  private applyPendingIncidentFocus(): void {
    if (!this.pendingIncidentId) return;
    const feature = this.activeIncidentSource
      .getFeatures()
      .find((item) => item.get('incidentId') === this.pendingIncidentId);
    if (!feature) {
      this.pendingIncidentId = undefined;
      return;
    }
    const size = this.map.getSize();
    const geometry = feature.getGeometry();
    if (!size || size[0] <= 0 || size[1] <= 0 || !geometry) return;
    this.pendingIncidentId = undefined;
    const view = this.map.getView();
    view.cancelAnimations();
    view.fit(geometry.getExtent(), {
      duration: reducedMotionPreferred() ? 0 : 400,
      padding: fitPadding(size),
      maxZoom: 9,
      size,
    });
  }

  private reportView(): void {
    const center = this.map.getView().getCenter();
    if (!center) {
      return;
    }
    const [longitude, latitude] = toLonLat(center);
    this.options.onViewChange({
      centerLatitude: latitude,
      centerLongitude: longitude,
      zoom: this.map.getView().getZoom() ?? this.options.initialView.zoom,
    });
  }

  private clearCommonOperationalPicture(): void {
    for (const layer of this.copLayers) this.map.removeLayer(layer);
    this.copLayers = [];
  }

  private clearSatelliteImagery(): void {
    if (this.satelliteLayer) this.map.removeLayer(this.satelliteLayer);
    this.satelliteLayer = undefined;
  }
}

function validOpacity(opacity: number): boolean {
  return Number.isFinite(opacity) && opacity >= 0 && opacity <= 1;
}

function validAreaBounds(bounds: MapAreaBounds): boolean {
  const [minLongitude, minLatitude, maxLongitude, maxLatitude] = bounds;
  return (
    bounds.every(Number.isFinite) &&
    minLongitude >= -180 &&
    minLongitude <= 180 &&
    maxLongitude >= minLongitude &&
    maxLongitude - minLongitude <= 360 &&
    minLatitude >= -90 &&
    maxLatitude <= 90 &&
    maxLatitude >= minLatitude
  );
}

function validMaxZoom(maxZoom: number): boolean {
  return Number.isFinite(maxZoom) && maxZoom >= 2 && maxZoom <= 18;
}

function projectedExtent(bounds: MapAreaBounds): number[] | undefined {
  const [minLongitude, minLatitude, maxLongitude, maxLatitude] = bounds;
  const minimum = fromLonLat([
    minLongitude,
    Math.max(minLatitude, -WEB_MERCATOR_MAX_LATITUDE),
  ]);
  const maximum = fromLonLat([
    maxLongitude,
    Math.min(maxLatitude, WEB_MERCATOR_MAX_LATITUDE),
  ]);
  const extent = [
    Math.min(minimum[0], maximum[0]),
    Math.min(minimum[1], maximum[1]),
    Math.max(minimum[0], maximum[0]),
    Math.max(minimum[1], maximum[1]),
  ];
  return extent.every(Number.isFinite) ? extent : undefined;
}

function fitPadding(size: readonly number[]): [number, number, number, number] {
  const horizontal = Math.min(DEFAULT_FIT_PADDING, Math.max(0, (size[0] - 1) / 2));
  const vertical = Math.min(DEFAULT_FIT_PADDING, Math.max(0, (size[1] - 1) / 2));
  return [vertical, horizontal, vertical, horizontal];
}

function reducedMotionPreferred(): boolean {
  return (
    typeof window !== 'undefined' &&
    typeof window.matchMedia === 'function' &&
    window.matchMedia('(prefers-reduced-motion: reduce)').matches
  );
}

function toOpenLayersGeometry(geometry: CopGeometry): Geometry {
  if (geometry.type === 'Point') {
    return new Point(fromLonLat(geometry.coordinates));
  }
  if (geometry.type === 'LineString') {
    return new LineString(geometry.coordinates.map((point) => fromLonLat(point)));
  }
  return new Polygon(
    geometry.coordinates.map((ring) => ring.map((point) => fromLonLat(point))),
  );
}

function toActiveIncidentGeometry(geometry: RenderableIncidentGeometry): Geometry {
  const coordinates = geometry.coordinates.map((point) =>
    fromLonLat([point.longitude, point.latitude]),
  );
  if (geometry.kind === 'point') return new Point(coordinates[0]);
  if (geometry.kind === 'track') return new LineString(coordinates);
  return new Polygon([coordinates]);
}

function styleForAuthority(value: unknown): Style {
  const authority: CopAuthority =
    value === 'official_source' || value === 'source_supplied'
      ? value
      : 'analytical_generated';
  const semantics = copStyleSemantics(authority);
  return new Style({
    stroke: new Stroke({
      color: semantics.strokeColor,
      width: authority === 'official_source' ? 3 : 2,
      lineDash: semantics.lineDash,
    }),
    fill: new Fill({ color: semantics.fillColor }),
    image: new CircleStyle({
      radius: authority === 'official_source' ? 7 : 6,
      fill: new Fill({ color: semantics.fillColor }),
      stroke: new Stroke({ color: semantics.strokeColor, width: 2 }),
    }),
  });
}

function styleForActiveIncident(value: unknown, selected = false): Style {
  const disaster = value as DisasterType;
  const color =
    disaster === 'earthquake'
      ? '#9f1239'
      : disaster === 'flood'
        ? '#0369a1'
        : disaster === 'wildfire'
          ? '#c2410c'
          : disaster === 'landslide'
            ? '#854d0e'
            : disaster === 'tropical_cyclone'
              ? '#6d28d9'
              : '#7f1d1d';
  return new Style({
    stroke: new Stroke({ color, width: selected ? 5 : 3 }),
    fill: new Fill({ color: `${color}26` }),
    image: new CircleStyle({
      radius: selected ? 10 : 7,
      fill: new Fill({ color }),
      stroke: new Stroke({ color: '#ffffff', width: selected ? 4 : 2 }),
    }),
  });
}
