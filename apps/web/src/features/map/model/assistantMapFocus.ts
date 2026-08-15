import type {
  CommonOperationalPicture,
  ConversationMessage,
  CopGeometry,
} from '@/shared/types/assistant';

export type MapAreaBounds = readonly [number, number, number, number];

export type AssistantMapAreaOfInterest = {
  id: string;
  bounds: MapAreaBounds;
};

// Mirrors the bounded country extents in the backend's packaged geography catalog.
// These are navigation extents only, not legal borders or new geocoding data.
const SUPPORTED_COUNTRIES: Readonly<
  Record<string, { code: string; bounds: MapAreaBounds }>
> = {
  JPN: { code: 'JPN', bounds: [122, 20, 154, 46] },
  JAPAN: { code: 'JPN', bounds: [122, 20, 154, 46] },
  VNM: { code: 'VNM', bounds: [102.14, 8.18, 109.47, 23.4] },
  VIETNAM: { code: 'VNM', bounds: [102.14, 8.18, 109.47, 23.4] },
  'VIET NAM': { code: 'VNM', bounds: [102.14, 8.18, 109.47, 23.4] },
  VEN: { code: 'VEN', bounds: [-73.35, 0.63, -59.8, 12.2] },
  VENEZUELA: { code: 'VEN', bounds: [-73.35, 0.63, -59.8, 12.2] },
};

export function assistantMapAreaOfInterest(
  messages: readonly ConversationMessage[],
): AssistantMapAreaOfInterest | undefined {
  const latestMessage = messages[messages.length - 1];
  if (!latestMessage || latestMessage.role !== 'assistant' || !latestMessage.report) {
    return undefined;
  }

  const cop = latestMessage.report.commonOperationalPicture;
  const copBounds = cop ? boundsForCommonOperationalPicture(cop) : undefined;
  if (cop && copBounds) {
    return {
      id: `${latestMessage.id}:cop:${cop.cop_id}`,
      bounds: copBounds,
    };
  }

  const selectedEvent = latestMessage.report.selectedEvent;
  const selectedEventPoint = selectedEvent
    ? wgs84Point(selectedEvent.longitude, selectedEvent.latitude)
    : undefined;
  if (selectedEvent && selectedEventPoint) {
    const [longitude, latitude] = selectedEventPoint;
    return {
      id: `${latestMessage.id}:event:${selectedEvent.event_id}`,
      bounds: [longitude, latitude, longitude, latitude],
    };
  }

  const country = latestMessage.report.investigation?.country?.trim();
  if (!country) {
    return undefined;
  }
  const supportedCountry = SUPPORTED_COUNTRIES[country.toUpperCase()];
  if (!supportedCountry) {
    return undefined;
  }
  return {
    id: `${latestMessage.id}:country:${supportedCountry.code}`,
    bounds: supportedCountry.bounds,
  };
}

function boundsForCommonOperationalPicture(
  cop: CommonOperationalPicture,
): MapAreaBounds | undefined {
  const longitudes: number[] = [];
  let minLatitude = Number.POSITIVE_INFINITY;
  let maxLatitude = Number.NEGATIVE_INFINITY;

  for (const layer of cop.layers) {
    for (const feature of layer.features) {
      for (const [longitude, latitude] of geometryCoordinates(feature.geometry)) {
        if (!validWgs84Coordinate(longitude, latitude)) {
          continue;
        }
        longitudes.push(longitude);
        minLatitude = Math.min(minLatitude, latitude);
        maxLatitude = Math.max(maxLatitude, latitude);
      }
    }
  }

  if (longitudes.length === 0) {
    return undefined;
  }
  const [minLongitude, maxLongitude] = smallestLongitudeInterval(longitudes);
  return [minLongitude, minLatitude, maxLongitude, maxLatitude];
}

function geometryCoordinates(geometry: CopGeometry): [number, number][] {
  if (geometry.type === 'Point') {
    return [geometry.coordinates];
  }
  if (geometry.type === 'LineString') {
    return geometry.coordinates;
  }
  return geometry.coordinates.flat();
}

function wgs84Point(
  longitude: number | null | undefined,
  latitude: number | null | undefined,
): [number, number] | undefined {
  if (
    typeof longitude !== 'number' ||
    !Number.isFinite(longitude) ||
    longitude < -180 ||
    longitude > 180 ||
    typeof latitude !== 'number' ||
    !Number.isFinite(latitude) ||
    latitude < -90 ||
    latitude > 90
  ) {
    return undefined;
  }
  return [longitude, latitude];
}

function validWgs84Coordinate(
  longitude: number | null | undefined,
  latitude: number | null | undefined,
): boolean {
  return wgs84Point(longitude, latitude) !== undefined;
}

function smallestLongitudeInterval(longitudes: readonly number[]): [number, number] {
  const sorted = longitudes
    .map((longitude) => ((longitude + 180) % 360) - 180)
    .sort((first, second) => first - second);
  if (sorted.length === 1) {
    return [sorted[0], sorted[0]];
  }

  let largestGap = Number.NEGATIVE_INFINITY;
  let intervalStart = sorted[0];
  let intervalEnd = sorted[sorted.length - 1];
  for (let index = 0; index < sorted.length; index += 1) {
    const current = sorted[index];
    const next = index === sorted.length - 1 ? sorted[0] + 360 : sorted[index + 1];
    const gap = next - current;
    if (gap > largestGap) {
      largestGap = gap;
      intervalStart = next;
      intervalEnd = current + 360;
    }
  }
  while (intervalStart > 180) {
    intervalStart -= 360;
    intervalEnd -= 360;
  }
  return [intervalStart, intervalEnd];
}
