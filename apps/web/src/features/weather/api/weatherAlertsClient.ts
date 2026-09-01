import type {
  WeatherAlert,
  WeatherAlertGeometry,
  WeatherAlertsSnapshot,
} from '@/features/weather/model/weatherAlert';
import { matchesApiSchema } from '@/shared/api/generated/assistant';
import { API_BASE_URL } from '@/shared/config/runtime';

export async function fetchWeatherAlerts(
  signal?: AbortSignal,
): Promise<WeatherAlertsSnapshot> {
  const response = await fetch(`${API_BASE_URL}/weather-alerts`, { signal });
  if (!response.ok) {
    throw new Error(`Weather alerts request failed with status ${response.status}.`);
  }
  const body = (await response.json()) as unknown;
  if (!matchesApiSchema('WeatherAlertsSnapshotResponse', body)) {
    throw new Error('Weather alerts returned an invalid response.');
  }
  const typed = body as WeatherAlertsSnapshot;
  return {
    ...typed,
    alerts: typed.alerts.map(parseAlert),
  };
}

function parseAlert(value: WeatherAlert): WeatherAlert {
  if (value.canonical_url && !validCanonicalUrl(value.canonical_url)) {
    throw new Error('Weather alert canonical URL is invalid.');
  }
  return { ...value, geometry: parseGeometry(value.geometry) } as WeatherAlert;
}

function parseGeometry(value: unknown): WeatherAlertGeometry | null {
  if (value === null) return null;
  if (!isRecord(value) || value.kind !== 'polygon' || !Array.isArray(value.rings)) {
    throw new Error('Weather alert geometry is invalid.');
  }
  const rings = value.rings.map((ring) => {
    if (!Array.isArray(ring) || ring.length < 4) {
      throw new Error('Weather alert geometry has an invalid ring.');
    }
    const coordinates = ring.map((coordinate) => {
      if (
        !isRecord(coordinate) ||
        typeof coordinate.latitude !== 'number' ||
        !Number.isFinite(coordinate.latitude) ||
        coordinate.latitude < -90 ||
        coordinate.latitude > 90 ||
        typeof coordinate.longitude !== 'number' ||
        !Number.isFinite(coordinate.longitude) ||
        coordinate.longitude < -180 ||
        coordinate.longitude > 180
      ) {
        throw new Error('Weather alert geometry has an invalid coordinate.');
      }
      return { latitude: coordinate.latitude, longitude: coordinate.longitude };
    });
    const first = coordinates[0];
    const last = coordinates.at(-1);
    if (
      !last ||
      first.latitude !== last.latitude ||
      first.longitude !== last.longitude
    ) {
      throw new Error('Weather alert geometry ring is not closed.');
    }
    return coordinates;
  });
  return { kind: 'polygon', rings };
}

function validCanonicalUrl(value: string): boolean {
  try {
    const target = new URL(value);
    return (
      target.protocol === 'https:' &&
      target.hostname === 'api.weather.gov' &&
      target.username === '' &&
      target.password === '' &&
      target.port === '' &&
      target.pathname.startsWith('/alerts/')
    );
  } catch {
    return false;
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null;
}
