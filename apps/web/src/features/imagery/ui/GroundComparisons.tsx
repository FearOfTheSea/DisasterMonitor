'use client';

/* eslint-disable @next/next/no-img-element -- Comparison tiles are dynamic evidence URLs and must not be transformed. */

import { useState } from 'react';

import {
  comparisonForSensor,
  formatImageryTime,
  sensorStatus,
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
  const prepared = request.artifacts
    ?.map((artifact) => ({
      artifact,
      selection: request.sensors
        .flatMap((sensor) => sensor.selections)
        .find((selection) => selection.selection_id === artifact.selection_id),
    }))
    .filter((item) => item.selection?.observation)
    .sort(
      (a, b) => previewPriority(a.artifact.role) - previewPriority(b.artifact.role),
    )[0];
  if (comparisons.length === 0)
    return (
      <section
        className="ground-imagery-section ground-imagery-comparisons"
        aria-label="Ground comparisons"
      >
        {prepared?.selection ? (
          <>
            <div className="ground-imagery-section-heading">
              <div>
                <h3>Prepared observation</h3>
                <p>
                  {SENSOR_LABELS[prepared.artifact.sensor]} ·{' '}
                  {formatImageryTime(prepared.selection.observation?.captured_start)}
                </p>
              </div>
              <span className="ground-imagery-status is-positive">Image ready</span>
            </div>
            <figure className="ground-single-preview">
              <img
                src={previewUrl(prepared.artifact.artifact_id)}
                alt={`${SENSOR_LABELS[prepared.artifact.sensor]} ${prepared.artifact.role === 'pre_event_reference' ? 'before' : 'after'} capture`}
              />
              <figcaption>
                {prepared.artifact.role === 'pre_event_reference' ? 'Before' : 'After'}{' '}
                · {formatImageryTime(prepared.selection.observation?.captured_start)}
              </figcaption>
            </figure>
            <p>
              This single capture provides visual context. It does not establish damage
              or safety. The patterned area has no pixels from this capture. Regional
              image quality has not been assessed unless stated in the selection
              details.
            </p>
          </>
        ) : (
          <>
            <h3>Comparison stage</h3>
            <p>
              A validated before and after image pair is not available yet. These are
              catalog outcomes, not evidence of damage or safety outside observed areas.
            </p>
          </>
        )}
        <div className="ground-comparison-status-grid">
          {DISPLAY_SENSORS.map((sensor) => {
            const status = sensorStatus(request, sensor);
            const after =
              status?.selections.find(
                (selection) => selection.role === 'first_useful_after_onset',
              ) ??
              status?.selections.find(
                (selection) => selection.role === 'latest_useful',
              );
            return (
              <article key={sensor} className="ground-comparison-status-card">
                <strong>{SENSOR_LABELS[sensor]}</strong>
                <small>
                  {status
                    ? `${status.scanned_count} acquisitions scanned · ${status.scan_complete ? 'scan complete' : 'scan incomplete'}`
                    : 'Catalog status unavailable'}
                </small>
                <p>
                  {after?.observation
                    ? `After-onset capture catalogued at ${formatImageryTime(after.observation.captured_start)}; no validated comparison artifact yet.`
                    : (after?.explanation ??
                      status?.failure_detail ??
                      'No role result returned.')}
                </p>
              </article>
            );
          })}
        </div>
      </section>
    );
  return (
    <section
      className="ground-imagery-section ground-imagery-comparisons"
      aria-label="Ground comparisons"
    >
      <div className="ground-imagery-section-heading">
        <div>
          <h3>Matched before / after</h3>
          <p>Both views use the same grid and synchronized viewport.</p>
        </div>
        <span className="ground-imagery-status is-positive">Comparable</span>
      </div>
      {comparisons.map(({ sensor, pair }) => (
        <GroundComparisonCard key={sensor} sensor={sensor} pair={pair!} />
      ))}
    </section>
  );
}

function previewPriority(role: string): number {
  if (role === 'first_useful_after_onset') return 0;
  if (role === 'latest_useful') return 1;
  return 2;
}

function GroundComparisonCard({
  sensor,
  pair,
}: {
  sensor: Sensor;
  pair: NonNullable<ReturnType<typeof comparisonForSensor>>;
}) {
  const [mode, setMode] = useState<'side-by-side' | 'swipe'>('side-by-side');
  const [position, setPosition] = useState(50);
  const beforeUrl = previewUrl(pair.before.artifact_id);
  const afterUrl = previewUrl(pair.after.artifact_id);
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

function previewUrl(artifactId: string): string {
  return `${API_BASE_URL}/ground-imagery/artifacts/${encodeURIComponent(artifactId)}/preview.png`;
}
