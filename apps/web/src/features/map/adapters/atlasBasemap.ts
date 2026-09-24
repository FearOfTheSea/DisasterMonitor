import GeoJSON from 'ol/format/GeoJSON';
import MultiPolygon from 'ol/geom/MultiPolygon';
import Polygon from 'ol/geom/Polygon';
import Graticule from 'ol/layer/Graticule';
import VectorLayer from 'ol/layer/Vector';
import VectorSource from 'ol/source/Vector';
import { Fill, Stroke, Style, Text } from 'ol/style';

const land = new Fill({ color: '#203743' });
const border = new Stroke({ color: '#49616c', width: 0.65 });
const coastline = new Stroke({ color: '#67818b', width: 0.9 });

function countryLayer(url: string, onError?: () => void, onReady?: () => void) {
  const source = new VectorSource({ url, format: new GeoJSON() });
  const labelPoints = new WeakMap<object, ReturnType<Polygon['getInteriorPoint']>>();
  source.on('featuresloaderror', () => onError?.());
  source.on('featuresloadend', () => onReady?.());
  return new VectorLayer({
    source,
    declutter: true,
    style: (feature, resolution) => {
      const name = feature.get('NAME_EN') ?? feature.get('ADMIN');
      const labelRank = Number(feature.get('LABELRANK'));
      const showLabel = resolution < 65000 && labelRank <= (resolution > 20000 ? 2 : 4);
      const geography = new Style({
        fill: land,
        stroke: resolution < 30000 ? border : coastline,
      });
      if (!showLabel || typeof name !== 'string') return geography;
      const geometry = feature.getGeometry();
      if (!geometry) return geography;
      let labelPoint = labelPoints.get(geometry);
      if (!labelPoint) {
        const polygon =
          geometry instanceof MultiPolygon
            ? geometry
                .getPolygons()
                .reduce<Polygon | undefined>(
                  (largest, current) =>
                    !largest || current.getArea() > largest.getArea()
                      ? current
                      : largest,
                  undefined,
                )
            : geometry instanceof Polygon
              ? geometry
              : undefined;
        if (!polygon) return geography;
        labelPoint = polygon.getInteriorPoint();
        labelPoints.set(geometry, labelPoint);
      }
      return [
        geography,
        new Style({
          geometry: labelPoint,
          text: new Text({
            text: name,
            font: '500 11px Inter, sans-serif',
            fill: new Fill({ color: '#9cb4be' }),
            stroke: new Stroke({ color: '#203743', width: 2 }),
            overflow: false,
          }),
        }),
      ];
    },
  });
}

export function createAtlasBasemap(onError?: () => void, onReady?: () => void) {
  const countries = countryLayer(
    '/atlas/ne_110m_admin_0_countries.geojson',
    onError,
    onReady,
  );
  countries.set('dmLayerType', 'base');
  countries.setZIndex(0);
  const detailedCountries = countryLayer(
    '/atlas/ne_50m_admin_0_countries.geojson',
    onError,
  );
  detailedCountries.set('dmLayerType', 'base');
  detailedCountries.setZIndex(0);
  detailedCountries.setVisible(false);
  const marine = new VectorLayer({
    source: new VectorSource({
      url: '/atlas/ne_110m_geography_marine_polys.geojson',
      format: new GeoJSON(),
    }),
    declutter: true,
    style: (feature, resolution) => {
      if (resolution < 10000 || feature.get('featurecla') !== 'ocean') return undefined;
      const name = feature.get('name_en') ?? feature.get('name');
      return typeof name === 'string'
        ? new Style({
            text: new Text({
              text: name,
              font: 'italic 12px Inter, sans-serif',
              fill: new Fill({ color: '#7eabbf' }),
              stroke: new Stroke({ color: '#08151d', width: 3 }),
            }),
          })
        : undefined;
    },
  });
  marine.setZIndex(1);
  const graticule = new Graticule({
    strokeStyle: new Stroke({ color: 'rgba(105, 140, 153, 0.2)', width: 0.6 }),
    showLabels: false,
    wrapX: false,
  });
  graticule.setZIndex(-1);
  return { countries, detailedCountries, marine, graticule };
}
