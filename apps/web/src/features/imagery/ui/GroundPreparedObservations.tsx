'use client';

/* eslint-disable @next/next/no-img-element -- Evidence previews must retain their source URLs. */

import { useState } from 'react';

import { GroundCoverageMap } from '@/features/imagery/ui/GroundCoverageMap';
import {
  captureRelationship,
  formatImageryTime,
  SENSOR_LABELS,
  type GroundImageryPanelRequest,
} from '@/features/imagery/model/groundImagery';
import { API_BASE_URL } from '@/shared/config/runtime';

export function GroundPreparedObservations({
  request,
}: {
  request: GroundImageryPanelRequest;
}) {
  const [choice, setChoice] = useState<{ version: number; artifactId: string }>();
  const selections = request.sensors.flatMap((sensor) => sensor.selections);
  const manual = new Set(
    selections
      .filter((item) => item.reason === 'operator_selected')
      .map((item) => item.selection_id),
  );
  const prepared = (request.artifacts ?? [])
    .map((artifact) => ({
      artifact,
      observation:
        selections.find((item) => item.selection_id === artifact.selection_id)
          ?.observation ?? artifact.observation,
    }))
    .filter((item) => item.observation)
    .toSorted(
      (a, b) =>
        Number(manual.has(b.artifact.selection_id)) -
          Number(manual.has(a.artifact.selection_id)) ||
        qualityPriority(a.observation!.quality?.quality_state) -
          qualityPriority(b.observation!.quality?.quality_state) ||
        new Date(b.observation!.captured_end).getTime() -
          new Date(a.observation!.captured_end).getTime(),
    );
  const selected =
    (choice?.version === request.request_version
      ? prepared.find((item) => item.artifact.artifact_id === choice.artifactId)
      : undefined) ?? prepared[0];
  const observation = selected?.observation;
  if (!selected || !observation)
    return (
      <>
        <h3>Comparison stage</h3>
        <p>
          A validated before and after image pair is not available yet. These are
          catalog outcomes, not evidence of damage or safety outside observed areas.
        </p>
      </>
    );
  const artifact = selected.artifact;
  return (
    <section aria-label="Prepared observation">
      <div className="ground-imagery-section-heading">
        <div>
          <h3>Prepared observation</h3>
          <p>
            {SENSOR_LABELS[artifact.sensor]} ·{' '}
            {formatImageryTime(observation.captured_start)}
          </p>
        </div>
        <span
          className={`ground-imagery-status ${observation.quality?.quality_state === 'useful' ? 'is-positive' : 'is-warning'}`}
        >
          {observation.quality?.usable_fraction === 0
            ? 'Artifact delivered; no usable pixels'
            : observation.quality?.quality_state === 'useful'
              ? 'Useful observation ready'
              : 'Artifact delivered; inspect regional quality'}
        </span>
      </div>
      <label className="ground-prepared-chooser">
        Prepared capture
        <select
          value={artifact.artifact_id}
          onChange={(event) =>
            setChoice({
              version: request.request_version,
              artifactId: event.target.value,
            })
          }
        >
          {prepared.map((item) => (
            <option key={item.artifact.artifact_id} value={item.artifact.artifact_id}>
              {item.observation!.product_id} ·{' '}
              {formatImageryTime(item.observation!.captured_start)} ·{' '}
              {item.observation!.quality?.quality_state ?? 'quality unassessed'}
            </option>
          ))}
        </select>
      </label>
      <figure className="ground-single-preview">
        <img
          src={`${API_BASE_URL}/ground-imagery/artifacts/${encodeURIComponent(artifact.artifact_id)}/preview.png`}
          alt={`${SENSOR_LABELS[artifact.sensor]} ${captureRelationship(request, observation)} capture`}
        />
        <figcaption>
          {captureRelationship(request, observation)} ·{' '}
          {formatImageryTime(observation.captured_start)} · {observation.product_id}
        </figcaption>
      </figure>
      <GroundCoverageMap
        artifact={artifact}
        observation={observation}
        region={request.region.region}
      />
      <p>
        This single capture provides visual context. It does not establish damage or
        safety. The patterned area has no pixels from this capture.
        {observation.quality
          ? ` Core assessment: ${Math.round(observation.quality.usable_fraction * 100)}% usable, ${Math.round(observation.quality.obscured_fraction * 100)}% obscured, ${Math.round(observation.quality.uncovered_fraction * 100)}% uncovered.`
          : ' Regional image quality has not been assessed.'}
      </p>
    </section>
  );
}

function qualityPriority(state: string | undefined): number {
  return (
    { useful: 0, partial: 1, uncertain: 3, obscured: 4, uncovered: 5 }[state ?? ''] ?? 2
  );
}
