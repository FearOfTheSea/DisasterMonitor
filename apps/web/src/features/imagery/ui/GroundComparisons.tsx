'use client';

/* eslint-disable @next/next/no-img-element -- Comparison tiles are dynamic evidence URLs and must not be transformed. */

import { useState } from 'react';

import {
  comparisonTile,
  type TileCoordinate,
} from '@/features/imagery/model/comparisonTile';
import {
  comparisonForSensor,
  formatImageryTime,
  SENSOR_LABELS,
  type GroundImageryPanelRequest,
} from '@/features/imagery/model/groundImagery';
import type { Sensor } from '@/shared/api/generated/assistant';
import { API_BASE_URL } from '@/shared/config/runtime';

const DISPLAY_SENSORS: Sensor[] = ['sentinel-1', 'sentinel-2'];

export function GroundComparisons({ request }: { request: GroundImageryPanelRequest }) {
  const comparisons = DISPLAY_SENSORS.map((sensor) => ({
    sensor,
    pair: comparisonForSensor(request, sensor),
  })).filter((value) => value.pair !== undefined);
  if (comparisons.length === 0) return null;
  return (
    <section className="ground-imagery-section" aria-label="Ground comparisons">
      <div className="ground-imagery-section-heading">
        <div>
          <h3>Matched before / after</h3>
          <p>Both views use the same grid and synchronized viewport.</p>
        </div>
        <span className="ground-imagery-status is-positive">Comparable</span>
      </div>
      {comparisons.map(({ sensor, pair }) => (
        <GroundComparisonCard
          key={sensor}
          sensor={sensor}
          pair={pair!}
          region={request.region.region?.inspection}
        />
      ))}
    </section>
  );
}

function GroundComparisonCard({
  sensor,
  pair,
  region,
}: {
  sensor: Sensor;
  pair: NonNullable<ReturnType<typeof comparisonForSensor>>;
  region: unknown;
}) {
  const [mode, setMode] = useState<'side-by-side' | 'swipe'>('side-by-side');
  const [position, setPosition] = useState(50);
  const tile = comparisonTile(region);
  const beforeUrl = tileUrl(pair.before.artifact_id, tile);
  const afterUrl = tileUrl(pair.after.artifact_id, tile);
  return (
    <article className="ground-comparison-card">
      <header>
        <div>
          <strong>{SENSOR_LABELS[sensor]}</strong>
          <small>
            {pair.beforeSelection.observation?.product_id} →{' '}
            {pair.afterSelection.observation?.product_id}
          </small>
        </div>
        <div className="ground-comparison-modes" aria-label="Comparison view mode">
          <button
            type="button"
            aria-pressed={mode === 'side-by-side'}
            onClick={() => setMode('side-by-side')}
          >
            Side by side
          </button>
          <button
            type="button"
            aria-pressed={mode === 'swipe'}
            onClick={() => setMode('swipe')}
          >
            Swipe
          </button>
        </div>
      </header>
      <div className={`ground-comparison-images is-${mode}`}>
        <figure>
          <img src={beforeUrl} alt={`${SENSOR_LABELS[sensor]} before capture`} />
          <figcaption>
            Before ·{' '}
            {formatImageryTime(pair.beforeSelection.observation?.captured_start)}
          </figcaption>
        </figure>
        <figure
          style={
            mode === 'swipe' ? { clipPath: `inset(0 0 0 ${position}%)` } : undefined
          }
        >
          <img src={afterUrl} alt={`${SENSOR_LABELS[sensor]} after capture`} />
          <figcaption>
            After · {formatImageryTime(pair.afterSelection.observation?.captured_start)}
          </figcaption>
        </figure>
      </div>
      {mode === 'swipe' ? (
        <label className="ground-comparison-slider">
          Reveal position
          <input
            aria-label="Reveal position"
            type="range"
            min="0"
            max="100"
            value={position}
            onChange={(event) => setPosition(Number(event.target.value))}
          />
        </label>
      ) : null}
      <p>
        Grid {pair.before.grid.crs} · {pair.before.grid.width} ×{' '}
        {pair.before.grid.height} · matching artifact grids are required. No comparison
        manifest or export has been generated for this display-only pairing.
      </p>
    </article>
  );
}

function tileUrl(artifactId: string, tile: TileCoordinate): string {
  return `${API_BASE_URL}/ground-imagery/artifacts/${encodeURIComponent(artifactId)}/tiles/${tile.zoom}/${tile.x}/${tile.y}.png`;
}
