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
import { fromLonLat, toLonLat } from 'ol/proj';
import { Circle as CircleStyle, Fill, Stroke, Style } from 'ol/style';

import {
  buildCopRenderPlan,
  copStyleSemantics,
  type CopAuthority,
} from '@/features/map/model/copRenderPlan';
import type {
  CommonOperationalPicture,
  CopGeometry,
  MapView,
} from '@/shared/types/assistant';

type MapAdapterOptions = {
  target: HTMLElement;
  initialView: MapView;
  onViewChange: (view: MapView) => void;
};

export class OpenLayersMapAdapter {
  private readonly map: Map;
  private copLayers: VectorLayer<VectorSource<Feature<Geometry>>>[] = [];

  constructor(private readonly options: MapAdapterOptions) {
    const baseLayer = new TileLayer({ source: new OSM() });
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
    this.map = new Map({
      target: options.target,
      layers: [baseLayer],
      view,
    });
    view.on('change:center', () => this.reportView());
    view.on('change:resolution', () => this.reportView());
  }

  destroy(): void {
    this.clearCommonOperationalPicture();
    this.map.setTarget(undefined);
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
      this.map.addLayer(layer);
      this.copLayers.push(layer);
    }
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
