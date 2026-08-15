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
const SUPPORTED_COUNTRY_BOUNDS: Readonly<Record<string, MapAreaBounds>> = {
  Japan: [122, 20, 154, 46],
  Vietnam: [102.14, 8.18, 109.47, 23.4],
  Venezuela: [-73.35, 0.63, -59.8, 12.2],
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

  const country = latestMessage.report.investigation?.country;
  if (!country) {
    return undefined;
  }
  const bounds = SUPPORTED_COUNTRY_BOUNDS[country];
  if (!bounds) {
    return undefined;
  }
  return {
    id: `${latestMessage.id}:country:${country}`,
    bounds,
  };
}

function boundsForCommonOperationalPicture(
  cop: CommonOperationalPicture,
): MapAreaBounds | undefined {
  let minLongitude = Number.POSITIVE_INFINITY;
  let minLatitude = Number.POSITIVE_INFINITY;
  let maxLongitude = Number.NEGATIVE_INFINITY;
  let maxLatitude = Number.NEGATIVE_INFINITY;

  for (const layer of cop.layers) {
    for (const feature of layer.features) {
      for (const [longitude, latitude] of geometryCoordinates(feature.geometry)) {
        if (!Number.isFinite(longitude) || !Number.isFinite(latitude)) {
          continue;
        }
        minLongitude = Math.min(minLongitude, longitude);
        minLatitude = Math.min(minLatitude, latitude);
        maxLongitude = Math.max(maxLongitude, longitude);
        maxLatitude = Math.max(maxLatitude, latitude);
      }
    }
  }

  if (!Number.isFinite(minLongitude)) {
    return undefined;
  }
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
