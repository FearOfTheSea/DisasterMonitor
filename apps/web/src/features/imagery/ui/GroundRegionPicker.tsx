'use client';

import { useState, type FormEvent } from 'react';

import { circular } from 'ol/geom/Polygon';

import type { GroundImageryRegionRequest } from '@/shared/api/generated/assistant';

type GroundRegion = GroundImageryRegionRequest['region'];

export function GroundRegionPicker({
  busy,
  onChoose,
}: {
  busy: boolean;
  onChoose: (region: GroundRegion) => void;
}) {
  const [latitude, setLatitude] = useState('');
  const [longitude, setLongitude] = useState('');
  const [radiusKm, setRadiusKm] = useState(15);
  const [error, setError] = useState<string>();

  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const lat = Number(latitude);
    const lon = Number(longitude);
    if (
      !latitude.trim() ||
      !longitude.trim() ||
      !Number.isFinite(lat) ||
      !Number.isFinite(lon) ||
      Math.abs(lat) > 80 ||
      Math.abs(lon) > 180
    ) {
      setError('Enter a center between 80°S and 80°N, and 180°W and 180°E.');
      return;
    }
    const coordinates = circular([lon, lat], radiusKm * 1_000, 64).getCoordinates();
    if (
      coordinates[0].some(
        ([ringLon, ringLat]) => Math.abs(ringLon) > 180 || Math.abs(ringLat) > 90,
      )
    ) {
      setError('This area crosses the date line or a pole. Choose a smaller radius.');
      return;
    }
    setError(undefined);
    onChoose({
      type: 'MultiPolygon',
      coordinates: [coordinates],
    });
  };

  return (
    <form className="ground-region-picker" onSubmit={submit}>
      <p>
        Enter a known location near the affected area. The circle is an inspection area
        you selected, not a measured impact boundary.
      </p>
      <div className="ground-region-picker-fields">
        <label>
          Center latitude
          <input
            type="number"
            min="-80"
            max="80"
            step="any"
            required
            value={latitude}
            onChange={(event) => setLatitude(event.target.value)}
          />
        </label>
        <label>
          Center longitude
          <input
            type="number"
            min="-180"
            max="180"
            step="any"
            required
            value={longitude}
            onChange={(event) => setLongitude(event.target.value)}
          />
        </label>
        <label>
          Radius
          <select
            value={radiusKm}
            onChange={(event) => setRadiusKm(Number(event.target.value))}
          >
            <option value="5">5 km</option>
            <option value="15">15 km</option>
            <option value="30">30 km</option>
          </select>
        </label>
      </div>
      {error ? <p role="alert">{error}</p> : null}
      <button type="submit" disabled={busy}>
        {busy ? 'Searching area…' : 'Search this area'}
      </button>
    </form>
  );
}
