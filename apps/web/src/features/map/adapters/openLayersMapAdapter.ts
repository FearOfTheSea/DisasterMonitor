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
import Cluster from 'ol/source/Cluster';
import VectorSource from 'ol/source/Vector';
import XYZ from 'ol/source/XYZ';
import { fromLonLat, toLonLat } from 'ol/proj';
import { createEmpty, extend } from 'ol/extent';
import { Circle as CircleStyle, Fill, Stroke, Style, Text } from 'ol/style';

import {
  buildCopRenderPlan,
  copStyleSemantics,
  type CopAuthority,
} from '@/features/map/model/copRenderPlan';
import type {
  ActiveIncidentMapFeature,
  RenderableIncidentGeometry,
} from '@/features/map/model/activeIncidentMap';
import { partitionActiveIncidentMapFeatures } from '@/features/map/model/activeIncidentMap';
import type { DisasterType } from '@/features/incidents/model/activeIncidents';
import type { MapAreaBounds } from '@/features/map/model/assistantMapFocus';
import { cycloneStyleSemantics } from '@/features/map/model/cycloneMapLayers';
import type { MapLayerId } from '@/features/map/model/mapLayerRegistry';
import {
  createDefaultMapLayerState,
  type MapLayerVisibility,
} from '@/features/map/model/mapLayerState';
import type {
  CommonOperationalPicture,
  CopGeometry,
  CycloneMapLayer,
  MapView,
} from '@/shared/types/assistant';
import type { WeatherAlert } from '@/features/weather/model/weatherAlert';

type MapAdapterOptions = {
  target: HTMLElement;
  initialView: MapView;
  onViewChange: (view: MapView) => void;
  onSelectIncident: (incidentId: string) => void;
  onSelectIncidentCluster?: (incidentIds: string[]) => void;
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
const INCIDENT_CLUSTER_MAX_ZOOM = 9;

type PendingArea = {
  bounds: MapAreaBounds;
  maxZoom: number;
};

export class OpenLayersMapAdapter {
  private readonly map: Map;
  private readonly pointIncidentSource: VectorSource<Feature<Geometry>>;
  private readonly clusteredIncidentSource: Cluster<Feature<Geometry>>;
  private readonly clusteredIncidentLayer: VectorLayer<Cluster<Feature<Geometry>>>;
  private readonly sourceGeometryIncidentSource: VectorSource<Feature<Geometry>>;
  private readonly sourceGeometryIncidentLayer: VectorLayer<
    VectorSource<Feature<Geometry>>
  >;
  private readonly weatherAlertSource: VectorSource<Feature<Geometry>>;
  private readonly weatherAlertLayer: VectorLayer<VectorSource<Feature<Geometry>>>;
  private satelliteLayer?: TileLayer<XYZ>;
  private copLayers: VectorLayer<VectorSource<Feature<Geometry>>>[] = [];
  private cycloneLayers: VectorLayer<VectorSource<Feature<Geometry>>>[] = [];
  private pendingArea?: PendingArea;
  private pendingIncidentId?: string;
  private layerVisibility: MapLayerVisibility = createDefaultMapLayerState().visibility;
  private applyingView = false;

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
    this.pointIncidentSource = new VectorSource<Feature<Geometry>>();
    this.clusteredIncidentSource = new Cluster({
      distance: 44,
      minDistance: 12,
      source: this.pointIncidentSource,
    });
    this.clusteredIncidentLayer = new VectorLayer({
      source: this.clusteredIncidentSource,
      style: (feature) =>
        styleForIncidentCluster(
          feature instanceof Feature ? clusterMembers(feature) : [],
        ),
    });
    this.clusteredIncidentLayer.set('dmLayerType', 'active-incidents');
    this.clusteredIncidentLayer.set('dmLayerId', 'active-incidents');
    this.clusteredIncidentLayer.set('dmIncidentRepresentation', 'clustered-points');
    this.clusteredIncidentLayer.setZIndex(10);
    this.sourceGeometryIncidentSource = new VectorSource<Feature<Geometry>>();
    this.sourceGeometryIncidentLayer = new VectorLayer({
      source: this.sourceGeometryIncidentSource,
      style: (feature) =>
        styleForActiveIncident(
          feature.get('disaster'),
          feature.get('selected') === true,
        ),
    });
    this.sourceGeometryIncidentLayer.set('dmLayerType', 'active-incidents');
    this.sourceGeometryIncidentLayer.set('dmLayerId', 'active-incidents');
    this.sourceGeometryIncidentLayer.set('dmIncidentRepresentation', 'source-geometry');
    this.sourceGeometryIncidentLayer.setZIndex(11);
    this.weatherAlertSource = new VectorSource<Feature<Geometry>>();
    this.weatherAlertLayer = new VectorLayer({
      source: this.weatherAlertSource,
      style: (feature) => styleForWeatherAlert(feature.get('severity')),
    });
    this.weatherAlertLayer.set('dmLayerType', 'authoritative-weather-alerts');
    this.weatherAlertLayer.set('dmLayerId', 'authoritative-weather-alerts');
    this.weatherAlertLayer.setVisible(
      this.layerVisibility['authoritative-weather-alerts'],
    );
    this.weatherAlertLayer.setZIndex(14);
    this.map = new Map({
      target: options.target,
      layers: [
        baseLayer,
        this.clusteredIncidentLayer,
        this.sourceGeometryIncidentLayer,
        this.weatherAlertLayer,
      ],
      view,
    });
    this.map.on('singleclick', (event) => {
      const hit = this.map.forEachFeatureAtPixel(
        event.pixel,
        (feature, layer) => ({ feature, layer }),
        {
          layerFilter: (layer) =>
            layer === this.clusteredIncidentLayer ||
            layer === this.sourceGeometryIncidentLayer,
        },
      );
      if (!hit) return;
      if (!(hit.feature instanceof Feature)) return;
      if (hit.layer === this.clusteredIncidentLayer) {
        const members = clusterMembers(hit.feature);
        const incidentIds = members
          .map((feature) => feature.get('incidentId'))
          .filter((value): value is string => typeof value === 'string')
          .toSorted();
        if (incidentIds.length === 1) {
          options.onSelectIncident(incidentIds[0]);
        } else if (incidentIds.length > 1) {
          this.expandIncidentCluster(members);
          options.onSelectIncidentCluster?.(incidentIds);
        }
        return;
      }
      const incidentId = hit.feature.get('incidentId');
      if (typeof incidentId === 'string') {
        options.onSelectIncident(incidentId);
      }
    });
    this.map.on('change:size', () => {
      this.applyPendingIncidentFocus();
      this.applyPendingArea();
    });
    view.on('change:center', () => {
      if (!this.applyingView) this.reportView();
    });
    view.on('change:resolution', () => {
      this.clusteredIncidentSource.setDistance(
        (view.getZoom() ?? options.initialView.zoom) < INCIDENT_CLUSTER_MAX_ZOOM
          ? 44
          : 0,
      );
      if (!this.applyingView) this.reportView();
    });
  }

  destroy(): void {
    this.pendingArea = undefined;
    this.pendingIncidentId = undefined;
    this.pointIncidentSource.clear();
    this.sourceGeometryIncidentSource.clear();
    this.weatherAlertSource.clear();
    this.clearSatelliteImagery();
    this.clearCommonOperationalPicture();
    this.clearCycloneMapLayers();
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
      layer.set('dmLayerId', 'cop-evidence');
      layer.setVisible(this.layerVisibility['cop-evidence']);
      layer.setZIndex(20);
      this.map.addLayer(layer);
      this.copLayers.push(layer);
    }
  }

  setCycloneMapLayers(layers: readonly CycloneMapLayer[]): void {
    this.clearCycloneMapLayers();
    for (const layerDefinition of layers) {
      const source = new VectorSource<Feature<Geometry>>({
        features: [
          new Feature({
            geometry: toCycloneMapGeometry(layerDefinition),
            layerId: layerDefinition.layer_id,
            semanticRole: layerDefinition.semantic_role,
            stormId: layerDefinition.storm_id,
          }),
        ],
      });
      const layer = new VectorLayer({
        source,
        style: () => styleForCycloneLayer(layerDefinition.semantic_role),
      });
      layer.set('dmLayerType', 'supplemental-cyclone');
      layer.set('dmLayerId', 'cyclone-supplemental');
      layer.set('dmCycloneLayerId', layerDefinition.layer_id);
      layer.setVisible(this.layerVisibility['cyclone-supplemental']);
      layer.setZIndex(15);
      this.map.addLayer(layer);
      this.cycloneLayers.push(layer);
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
    layer.set('dmLayerId', 'satellite-imagery');
    layer.set('dmSatelliteSourceId', configuration.sourceId);
    layer.setVisible(this.layerVisibility['satellite-imagery']);
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
    const partition = partitionActiveIncidentMapFeatures(incidents);
    this.pointIncidentSource.clear();
    this.sourceGeometryIncidentSource.clear();
    this.pointIncidentSource.addFeatures(
      partition.clusteredPoints.map(toActiveIncidentFeature),
    );
    this.sourceGeometryIncidentSource.addFeatures(
      partition.sourceGeometries.map(toActiveIncidentFeature),
    );
    this.applyPendingIncidentFocus();
  }

  setWeatherAlerts(alerts: readonly WeatherAlert[]): void {
    this.weatherAlertSource.clear();
    this.weatherAlertSource.addFeatures(
      alerts.flatMap((alert) => {
        if (!alert.geometry) return [];
        return [
          new Feature({
            geometry: new Polygon(
              alert.geometry.rings.map((ring) =>
                ring.map((point) => fromLonLat([point.longitude, point.latitude])),
              ),
            ),
            alertId: alert.provider_alert_id,
            severity: alert.severity,
            event: alert.event,
            publisher: alert.publisher,
          }),
        ];
      }),
    );
  }

  setView(next: MapView): void {
    if (!validMapView(next)) return;
    const view = this.map.getView();
    const currentCenter = view.getCenter();
    const current = currentCenter ? toLonLat(currentCenter) : undefined;
    const currentZoom = view.getZoom();
    if (
      current &&
      currentZoom !== undefined &&
      Math.abs(current[0] - next.centerLongitude) < 0.0001 &&
      Math.abs(current[1] - next.centerLatitude) < 0.0001 &&
      Math.abs(currentZoom - next.zoom) < 0.01
    ) {
      return;
    }
    this.applyingView = true;
    view.cancelAnimations();
    view.setCenter(fromLonLat([next.centerLongitude, next.centerLatitude]));
    view.setZoom(next.zoom);
    this.applyingView = false;
    this.reportView();
  }

  setSelectedIncident(incidentId?: string): void {
    for (const feature of this.incidentFeatures()) {
      feature.set('selected', feature.get('incidentId') === incidentId);
    }
    this.clusteredIncidentLayer.changed();
    this.sourceGeometryIncidentLayer.changed();
  }

  setLayerVisibility(visibility: MapLayerVisibility): void {
    this.layerVisibility = { ...visibility };
    for (const layer of this.map.getLayers().getArray()) {
      const layerId = layer.get('dmLayerId') as MapLayerId | undefined;
      if (layerId) layer.setVisible(visibility[layerId]);
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
    const feature = this.incidentFeatures().find(
      (item) => item.get('incidentId') === this.pendingIncidentId,
    );
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

  private incidentFeatures(): Feature<Geometry>[] {
    return [
      ...this.pointIncidentSource.getFeatures(),
      ...this.sourceGeometryIncidentSource.getFeatures(),
    ];
  }

  private expandIncidentCluster(features: readonly Feature<Geometry>[]): void {
    const size = this.map.getSize();
    if (!size || size[0] <= 0 || size[1] <= 0) return;
    const extent = createEmpty();
    for (const feature of features) {
      const geometry = feature.getGeometry();
      if (geometry) extend(extent, geometry.getExtent());
    }
    const view = this.map.getView();
    view.cancelAnimations();
    view.fit(extent, {
      duration: reducedMotionPreferred() ? 0 : 300,
      padding: fitPadding(size),
      maxZoom: 12,
      size,
    });
  }

  private clearCommonOperationalPicture(): void {
    for (const layer of this.copLayers) this.map.removeLayer(layer);
    this.copLayers = [];
  }

  private clearCycloneMapLayers(): void {
    for (const layer of this.cycloneLayers) this.map.removeLayer(layer);
    this.cycloneLayers = [];
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

function validMapView(view: MapView): boolean {
  return (
    Number.isFinite(view.centerLatitude) &&
    view.centerLatitude >= -90 &&
    view.centerLatitude <= 90 &&
    Number.isFinite(view.centerLongitude) &&
    view.centerLongitude >= -180 &&
    view.centerLongitude <= 180 &&
    Number.isFinite(view.zoom) &&
    view.zoom >= 2 &&
    view.zoom <= 18
  );
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

function toActiveIncidentFeature(
  incident: ActiveIncidentMapFeature,
): Feature<Geometry> {
  return new Feature({
    geometry: toActiveIncidentGeometry(incident.geometry),
    incidentId: incident.incidentId,
    disaster: incident.disaster,
  });
}

function clusterMembers(feature: Feature<Geometry>): Feature<Geometry>[] {
  const members = feature.get('features');
  return Array.isArray(members)
    ? members.filter((member): member is Feature<Geometry> => member instanceof Feature)
    : [];
}

function toActiveIncidentGeometry(geometry: RenderableIncidentGeometry): Geometry {
  const coordinates = geometry.coordinates.map((point) =>
    fromLonLat([point.longitude, point.latitude]),
  );
  if (geometry.kind === 'point') return new Point(coordinates[0]);
  if (geometry.kind === 'track') return new LineString(coordinates);
  return new Polygon([coordinates]);
}

function toCycloneMapGeometry(layer: CycloneMapLayer): Geometry {
  const coordinates = layer.coordinates.map((point) =>
    fromLonLat([point.longitude, point.latitude]),
  );
  if (layer.geometry_kind === 'point') return new Point(coordinates[0]);
  if (layer.geometry_kind === 'track') return new LineString(coordinates);
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

function styleForIncidentCluster(members: readonly Feature<Geometry>[]): Style {
  if (members.length === 1) {
    return styleForActiveIncident(
      members[0].get('disaster'),
      members[0].get('selected') === true,
    );
  }
  const selected = members.some((member) => member.get('selected') === true);
  return new Style({
    image: new CircleStyle({
      radius: selected ? 17 : 15,
      fill: new Fill({ color: '#172554' }),
      stroke: new Stroke({ color: selected ? '#fbbf24' : '#ffffff', width: 3 }),
    }),
    text: new Text({
      text: String(members.length),
      fill: new Fill({ color: '#ffffff' }),
      font: '700 12px system-ui, sans-serif',
    }),
  });
}

function styleForWeatherAlert(value: unknown): Style {
  const color =
    value === 'extreme'
      ? '#991b1b'
      : value === 'severe'
        ? '#b45309'
        : value === 'moderate'
          ? '#a16207'
          : value === 'minor'
            ? '#4d7c0f'
            : '#475569';
  return new Style({
    stroke: new Stroke({ color, width: 2.5, lineDash: [8, 4] }),
    fill: new Fill({ color: `${color}24` }),
  });
}

function styleForCycloneLayer(semanticRole: CycloneMapLayer['semantic_role']): Style {
  const semantics = cycloneStyleSemantics(semanticRole);
  return new Style({
    stroke: new Stroke({
      color: semantics.strokeColor,
      width: semanticRole === 'provisional_track' ? 3 : 2.5,
      lineDash: semantics.lineDash,
    }),
    fill: new Fill({ color: semantics.fillColor }),
    image: new CircleStyle({
      radius: semanticRole === 'forecast_track' ? 5 : 4,
      fill: new Fill({ color: semantics.fillColor }),
      stroke: new Stroke({ color: semantics.strokeColor, width: 2 }),
    }),
  });
}
