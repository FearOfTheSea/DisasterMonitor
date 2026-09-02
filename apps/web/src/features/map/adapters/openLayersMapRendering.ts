import Feature from 'ol/Feature';
import Geometry from 'ol/geom/Geometry';
import LineString from 'ol/geom/LineString';
import Point from 'ol/geom/Point';
import Polygon from 'ol/geom/Polygon';
import { fromLonLat } from 'ol/proj';
import { Circle as CircleStyle, Fill, Stroke, Style, Text } from 'ol/style';

import {
  copStyleSemantics,
  type CopAuthority,
} from '@/features/map/model/copRenderPlan';
import type {
  ActiveIncidentMapFeature,
  RenderableIncidentGeometry,
} from '@/features/map/model/activeIncidentMap';
import type { DisasterType } from '@/features/incidents/model/activeIncidents';
import type { MapAreaBounds } from '@/features/map/model/assistantMapFocus';
import { cycloneStyleSemantics } from '@/features/map/model/cycloneMapLayers';
import type { CopGeometry, CycloneMapLayer, MapView } from '@/shared/types/assistant';

const DEFAULT_FIT_PADDING = 56;
const WEB_MERCATOR_MAX_LATITUDE = 85.0511287798066;

export function validOpacity(opacity: number): boolean {
  return Number.isFinite(opacity) && opacity >= 0 && opacity <= 1;
}

export function validAreaBounds(bounds: MapAreaBounds): boolean {
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

export function validMaxZoom(maxZoom: number): boolean {
  return Number.isFinite(maxZoom) && maxZoom >= 2 && maxZoom <= 18;
}

export function validMapView(view: MapView): boolean {
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

export function projectedExtent(bounds: MapAreaBounds): number[] | undefined {
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

export function fitPadding(size: readonly number[]): [number, number, number, number] {
  const horizontal = Math.min(DEFAULT_FIT_PADDING, Math.max(0, (size[0] - 1) / 2));
  const vertical = Math.min(DEFAULT_FIT_PADDING, Math.max(0, (size[1] - 1) / 2));
  return [vertical, horizontal, vertical, horizontal];
}

export function reducedMotionPreferred(): boolean {
  return (
    typeof window !== 'undefined' &&
    typeof window.matchMedia === 'function' &&
    window.matchMedia('(prefers-reduced-motion: reduce)').matches
  );
}

export function toOpenLayersGeometry(geometry: CopGeometry): Geometry {
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

export function toActiveIncidentFeature(
  incident: ActiveIncidentMapFeature,
): Feature<Geometry> {
  return new Feature({
    geometry: toActiveIncidentGeometry(incident.geometry),
    incidentId: incident.incidentId,
    disaster: incident.disaster,
  });
}

export function clusterMembers(feature: Feature<Geometry>): Feature<Geometry>[] {
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

export function toCycloneMapGeometry(layer: CycloneMapLayer): Geometry {
  const coordinates = layer.coordinates.map((point) =>
    fromLonLat([point.longitude, point.latitude]),
  );
  if (layer.geometry_kind === 'point') return new Point(coordinates[0]);
  if (layer.geometry_kind === 'track') return new LineString(coordinates);
  return new Polygon([coordinates]);
}

export function styleForAuthority(value: unknown): Style {
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

export function styleForActiveIncident(value: unknown, selected = false): Style {
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

export function styleForIncidentCluster(members: readonly Feature<Geometry>[]): Style {
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

export function styleForWeatherAlert(value: unknown): Style {
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

export function styleForCycloneLayer(
  semanticRole: CycloneMapLayer['semantic_role'],
): Style {
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
