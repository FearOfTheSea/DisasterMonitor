export type SatelliteSourceId =
  | 'nasa-viirs-snpp-true-color'
  | 'nasa-modis-terra-true-color'
  | 'nasa-modis-aqua-true-color'
  | 'nasa-goes-east-geocolor'
  | 'nasa-goes-west-geocolor'
  | 'nasa-himawari-9-visible'
  | 'copernicus-sentinel-2-true-color'
  | 'planet-configured-mosaic';

export type SatelliteTemporalMode = 'daily' | 'subdaily' | 'fixed';

type DirectGibsAccess = {
  kind: 'direct-gibs';
  layerId: string;
  tileMatrixSet: string;
  format: 'jpeg' | 'png';
};

type DisasterMonitorApiAccess = {
  kind: 'disaster-monitor-api';
};

export type SatelliteImagerySource = {
  id: SatelliteSourceId;
  displayName: string;
  providerId: 'nasa-gibs' | 'copernicus-sentinel-hub' | 'planet';
  provider: string;
  temporalMode: SatelliteTemporalMode;
  temporalStepMinutes?: number;
  attribution: string;
  maximumUsefulZoom: number;
  available: boolean;
  access: DirectGibsAccess | DisasterMonitorApiAccess;
};

const GIBS_ATTRIBUTION =
  "We acknowledge the use of imagery provided by services from NASA's Global " +
  "Imagery Browse Services (GIBS), part of NASA's Earth Science Data and " +
  'Information System (ESDIS).';

export const SATELLITE_IMAGERY_SOURCES: readonly SatelliteImagerySource[] = [
  {
    id: 'nasa-viirs-snpp-true-color',
    displayName: 'NASA VIIRS Suomi-NPP True Color',
    providerId: 'nasa-gibs',
    provider: 'NASA GIBS',
    temporalMode: 'daily',
    attribution: GIBS_ATTRIBUTION,
    maximumUsefulZoom: 9,
    available: true,
    access: {
      kind: 'direct-gibs',
      layerId: 'VIIRS_SNPP_CorrectedReflectance_TrueColor',
      tileMatrixSet: 'GoogleMapsCompatible_Level9',
      format: 'jpeg',
    },
  },
  {
    id: 'nasa-modis-terra-true-color',
    displayName: 'NASA MODIS Terra True Color',
    providerId: 'nasa-gibs',
    provider: 'NASA GIBS',
    temporalMode: 'daily',
    attribution: GIBS_ATTRIBUTION,
    maximumUsefulZoom: 9,
    available: true,
    access: {
      kind: 'direct-gibs',
      layerId: 'MODIS_Terra_CorrectedReflectance_TrueColor',
      tileMatrixSet: 'GoogleMapsCompatible_Level9',
      format: 'jpeg',
    },
  },
  {
    id: 'nasa-modis-aqua-true-color',
    displayName: 'NASA MODIS Aqua True Color',
    providerId: 'nasa-gibs',
    provider: 'NASA GIBS',
    temporalMode: 'daily',
    attribution: GIBS_ATTRIBUTION,
    maximumUsefulZoom: 9,
    available: true,
    access: {
      kind: 'direct-gibs',
      layerId: 'MODIS_Aqua_CorrectedReflectance_TrueColor',
      tileMatrixSet: 'GoogleMapsCompatible_Level9',
      format: 'jpeg',
    },
  },
  {
    id: 'nasa-goes-east-geocolor',
    displayName: 'NASA GOES-East GeoColor',
    providerId: 'nasa-gibs',
    provider: 'NASA GIBS / NOAA',
    temporalMode: 'subdaily',
    temporalStepMinutes: 10,
    attribution: `${GIBS_ATTRIBUTION}; GOES data provided by NOAA`,
    maximumUsefulZoom: 7,
    available: true,
    access: {
      kind: 'direct-gibs',
      layerId: 'GOES-East_ABI_GeoColor',
      tileMatrixSet: 'GoogleMapsCompatible_Level7',
      format: 'png',
    },
  },
  {
    id: 'nasa-goes-west-geocolor',
    displayName: 'NASA GOES-West GeoColor',
    providerId: 'nasa-gibs',
    provider: 'NASA GIBS / NOAA',
    temporalMode: 'subdaily',
    temporalStepMinutes: 10,
    attribution: `${GIBS_ATTRIBUTION}; GOES data provided by NOAA`,
    maximumUsefulZoom: 7,
    available: true,
    access: {
      kind: 'direct-gibs',
      layerId: 'GOES-West_ABI_GeoColor',
      tileMatrixSet: 'GoogleMapsCompatible_Level7',
      format: 'png',
    },
  },
  {
    id: 'nasa-himawari-9-visible',
    displayName: 'NASA Himawari-9 visible imagery',
    providerId: 'nasa-gibs',
    provider: 'NASA GIBS / JMA',
    temporalMode: 'subdaily',
    temporalStepMinutes: 10,
    attribution: `${GIBS_ATTRIBUTION}; Himawari-9/AHI data provided by JMA`,
    maximumUsefulZoom: 7,
    available: true,
    access: {
      kind: 'direct-gibs',
      layerId: 'Himawari_AHI_Band3_Red_Visible_1km',
      tileMatrixSet: 'GoogleMapsCompatible_Level7',
      format: 'png',
    },
  },
  {
    id: 'copernicus-sentinel-2-true-color',
    displayName: 'Copernicus Sentinel-2 True Color',
    providerId: 'copernicus-sentinel-hub',
    provider: 'Copernicus Data Space / Sentinel Hub',
    temporalMode: 'daily',
    attribution:
      'Contains modified Copernicus Sentinel data; served through the configured Sentinel Hub service',
    maximumUsefulZoom: 14,
    available: false,
    access: { kind: 'disaster-monitor-api' },
  },
  {
    id: 'planet-configured-mosaic',
    displayName: 'Planet configured mosaic',
    providerId: 'planet',
    provider: 'Planet',
    temporalMode: 'fixed',
    attribution: '© Planet Labs PBC; configured mosaic',
    maximumUsefulZoom: 18,
    available: false,
    access: { kind: 'disaster-monitor-api' },
  },
];

const SOURCES_BY_ID = new Map(
  SATELLITE_IMAGERY_SOURCES.map((source) => [source.id, source]),
);

export function sourceById(id: string): SatelliteImagerySource {
  const source = SOURCES_BY_ID.get(id as SatelliteSourceId);
  if (!source) throw new Error(`Unknown satellite imagery source: ${id}`);
  return source;
}

export function observationTimeForSource(
  source: SatelliteImagerySource,
  now = new Date(),
): string | undefined {
  if (source.temporalMode === 'fixed') return undefined;
  if (source.temporalMode === 'daily') return now.toISOString().slice(0, 10);
  const step = source.temporalStepMinutes ?? 1;
  const rounded = new Date(now);
  rounded.setUTCMinutes(Math.floor(rounded.getUTCMinutes() / step) * step, 0, 0);
  return rounded.toISOString().replace('.000Z', 'Z');
}

export function validObservationTime(
  source: SatelliteImagerySource,
  value: string | undefined,
): boolean {
  if (source.temporalMode === 'fixed') return value === undefined;
  if (!value) return false;
  if (source.temporalMode === 'daily') return validDailyDate(value);
  const match = /^(\d{4}-\d{2}-\d{2})T(\d{2}):(\d{2}):00Z$/.exec(value);
  if (!match || !validDailyDate(match[1])) return false;
  const hour = Number(match[2]);
  const minute = Number(match[3]);
  const step = source.temporalStepMinutes ?? 1;
  return hour <= 23 && minute <= 59 && minute % step === 0;
}

export function buildNasaGibsTileUrl(
  sourceId: SatelliteSourceId,
  observationTime: string,
): string {
  const source = sourceById(sourceId);
  if (source.access.kind !== 'direct-gibs') {
    throw new Error('Protected satellite imagery must use the DisasterMonitor API.');
  }
  if (!validObservationTime(source, observationTime)) {
    const expected =
      source.temporalMode === 'daily'
        ? 'a valid daily date'
        : `a UTC date/time in ${source.temporalStepMinutes}-minute increments`;
    throw new Error(`Satellite imagery requires ${expected}.`);
  }
  const { layerId, tileMatrixSet, format } = source.access;
  return (
    `https://gibs.earthdata.nasa.gov/wmts/epsg3857/best/${layerId}/` +
    `default/${observationTime}/${tileMatrixSet}/{z}/{y}/{x}.${format}`
  );
}

function validDailyDate(value: string): boolean {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return false;
  const parsed = new Date(`${value}T00:00:00Z`);
  return !Number.isNaN(parsed.getTime()) && parsed.toISOString().slice(0, 10) === value;
}
