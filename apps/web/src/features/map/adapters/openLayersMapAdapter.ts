import Map from 'ol/Map';
import View from 'ol/View';
import TileLayer from 'ol/layer/Tile';
import OSM from 'ol/source/OSM';
import { fromLonLat, toLonLat } from 'ol/proj';

import type { MapView } from '@/shared/types/assistant';

type MapAdapterOptions = {
  target: HTMLElement;
  initialView: MapView;
  onViewChange: (view: MapView) => void;
};

export class OpenLayersMapAdapter {
  private readonly map: Map;

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
    this.map.setTarget(undefined);
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
}
