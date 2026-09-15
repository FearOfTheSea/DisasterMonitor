import { API_BASE_URL } from '@/shared/config/runtime';

export type ProductReference = {
  product_id: string;
  version: string;
  updated_at: string;
};

export type ShakeMapLayer = {
  product: ProductReference;
  measure: 'mmi' | 'pga' | 'pgv';
  unit: string;
  coverage_url: string;
  coverage_sha256: string | null;
  maximum: number | null;
  overlay_url: string | null;
  legend_url: string | null;
};

export type EarthquakeContext = {
  event_id: string;
  shakemap_layers: ShakeMapLayer[];
  pager: null | {
    product: ProductReference;
    alert_level: string;
    exposure_by_intensity: Array<{ intensity: number; population: number }>;
    fatality_probability_bins: Array<{
      minimum: number;
      maximum: number;
      probability: number;
      unit: string;
    }>;
    economic_loss_probability_bins: Array<{
      minimum: number;
      maximum: number;
      probability: number;
      unit: string;
    }>;
    interpretation: string;
  };
  ground_failure: Array<{
    kind: 'landslide' | 'liquefaction';
    product: ProductReference;
    shakemap_version: string;
    alert_level: string;
    interpretation: string;
  }>;
  aftershock_forecast: null | {
    product: ProductReference;
    model_name: string;
    advisory_time_frame: string;
    expires_at: string;
    global_scope: false;
    interpretation: string;
  };
  retrieved_at: string;
};

export async function fetchEarthquakeContext(
  eventId: string,
  signal?: AbortSignal,
): Promise<EarthquakeContext> {
  const response = await fetch(
    `${API_BASE_URL}/earthquakes/${encodeURIComponent(eventId)}/context`,
    { signal },
  );
  if (!response.ok) throw new Error(`USGS context failed with ${response.status}.`);
  const value = (await response.json()) as EarthquakeContext;
  if (!validContext(value, eventId)) throw new Error('USGS context is invalid.');
  return value;
}

function validContext(value: EarthquakeContext, eventId: string): boolean {
  return (
    value?.event_id === eventId &&
    Array.isArray(value.shakemap_layers) &&
    value.shakemap_layers.every(
      (layer) =>
        ['mmi', 'pga', 'pgv'].includes(layer.measure) &&
        validUsgsUrl(layer.coverage_url) &&
        (!layer.overlay_url || validUsgsUrl(layer.overlay_url)) &&
        (!layer.legend_url || validUsgsUrl(layer.legend_url)),
    ) &&
    Array.isArray(value.ground_failure)
  );
}

function validUsgsUrl(value: string): boolean {
  try {
    const url = new URL(value);
    return (
      url.protocol === 'https:' &&
      url.hostname === 'earthquake.usgs.gov' &&
      url.username === '' &&
      url.password === '' &&
      url.port === ''
    );
  } catch {
    return false;
  }
}
