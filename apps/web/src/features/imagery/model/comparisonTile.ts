export type TileCoordinate = { zoom: number; x: number; y: number };

export function comparisonTile(region: unknown): TileCoordinate {
  const points: [number, number][] = [];
  collectLonLat(region, points);
  if (points.length === 0) return { zoom: 0, x: 0, y: 0 };
  const west = Math.min(...points.map(([longitude]) => longitude));
  const east = Math.max(...points.map(([longitude]) => longitude));
  const south = Math.min(...points.map(([, latitude]) => latitude));
  const north = Math.max(...points.map(([, latitude]) => latitude));
  for (let zoom = 12; zoom >= 0; zoom -= 1) {
    const northwest = lonLatTile(west, north, zoom);
    const southeast = lonLatTile(east, south, zoom);
    if (northwest.x === southeast.x && northwest.y === southeast.y) return northwest;
  }
  return { zoom: 0, x: 0, y: 0 };
}

function collectLonLat(value: unknown, output: [number, number][]): void {
  if (!value || typeof value !== 'object' || !('coordinates' in value)) return;
  collectCoordinateArray((value as { coordinates: unknown }).coordinates, output);
}

function collectCoordinateArray(value: unknown, output: [number, number][]): void {
  if (!Array.isArray(value)) return;
  if (
    value.length >= 2 &&
    typeof value[0] === 'number' &&
    typeof value[1] === 'number' &&
    Number.isFinite(value[0]) &&
    Number.isFinite(value[1]) &&
    value[0] >= -180 &&
    value[0] <= 180 &&
    value[1] >= -90 &&
    value[1] <= 90
  ) {
    output.push([value[0], value[1]]);
    return;
  }
  value.forEach((item) => collectCoordinateArray(item, output));
}

function lonLatTile(longitude: number, latitude: number, zoom: number): TileCoordinate {
  const scale = 2 ** zoom;
  const boundedLatitude = Math.max(-85.0511, Math.min(85.0511, latitude));
  const x = Math.floor(((longitude + 180) / 360) * scale);
  const radians = (boundedLatitude * Math.PI) / 180;
  const y = Math.floor(((1 - Math.asinh(Math.tan(radians)) / Math.PI) / 2) * scale);
  return {
    zoom,
    x: Math.max(0, Math.min(scale - 1, x)),
    y: Math.max(0, Math.min(scale - 1, y)),
  };
}
