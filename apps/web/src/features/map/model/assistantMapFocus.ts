import type {
  CommonOperationalPicture,
  ConversationMessage,
  CopGeometry,
} from '@/shared/types/assistant';

export type MapAreaBounds = readonly [number, number, number, number];

export type AssistantMapAreaOfInterest = {
  id: string;
  bounds: MapAreaBounds;
  maxZoom?: number;
};

export function assistantMapAreaOfInterest(
  messages: readonly ConversationMessage[],
): AssistantMapAreaOfInterest | undefined {
  const latestMessage = messages[messages.length - 1];
  if (!latestMessage || latestMessage.role !== 'assistant') {
    return undefined;
  }

  if (latestMessage.mapAction) {
    return {
      id: `${latestMessage.id}:action:${latestMessage.mapAction.type}`,
      bounds: latestMessage.mapAction.bounds,
      maxZoom: latestMessage.mapAction.max_zoom,
    };
  }

  if (!latestMessage.report) {
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
  const selectedEventPoint =
    selectedEvent?.geometry?.kind === 'point'
      ? wgs84Point(
          selectedEvent.geometry.coordinates[0]?.longitude,
          selectedEvent.geometry.coordinates[0]?.latitude,
        )
      : undefined;
  if (selectedEvent && selectedEventPoint) {
    const [longitude, latitude] = selectedEventPoint;
    return {
      id: `${latestMessage.id}:event:${selectedEvent.event_id}`,
      bounds: [longitude, latitude, longitude, latitude],
    };
  }

  return undefined;
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
