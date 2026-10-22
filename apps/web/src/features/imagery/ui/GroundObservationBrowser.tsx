'use client';

import { useEffect, useRef, useState } from 'react';

import { fetchGroundImageryObservations } from '@/features/imagery/api/groundImageryClient';
import {
  formatFraction,
  formatImageryTime,
  labelImageryRole,
  SENSOR_LABELS,
} from '@/features/imagery/model/groundImagery';
import type {
  GroundImageryObservationPageResponse,
  GroundImagerySelectionRequest,
  GroundImagerySelectionResponse,
  Sensor,
} from '@/shared/api/generated/assistant';

type Props = {
  requestId: string;
  sensor: Sensor;
  selections: GroundImagerySelectionResponse[];
  busy: boolean;
  onSelect: (selection: GroundImagerySelectionRequest) => void;
};

export function GroundObservationBrowser({
  requestId,
  sensor,
  selections,
  busy,
  onSelect,
}: Props) {
  const [expanded, setExpanded] = useState(false);
  const [page, setPage] = useState<GroundImageryObservationPageResponse>();
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string>();
  const [role, setRole] = useState(
    selections.find((item) => item.role === 'latest_useful')?.role ??
      selections[0]?.role ??
      '',
  );
  const controller = useRef<AbortController | null>(null);
  useEffect(() => () => controller.current?.abort(), []);

  const load = async () => {
    controller.current?.abort();
    const pending = new AbortController();
    controller.current = pending;
    setLoading(true);
    setError(undefined);
    try {
      const next = await fetchGroundImageryObservations(
        requestId,
        sensor,
        page?.next_cursor ?? '0',
        pending.signal,
      );
      if (pending.signal.aborted) return;
      setPage((previous) => ({
        ...next,
        observations: [...(previous?.observations ?? []), ...next.observations],
      }));
    } catch (caught) {
      if (!pending.signal.aborted)
        setError(
          caught instanceof Error
            ? caught.message
            : 'Acquisitions could not be loaded.',
        );
    } finally {
      if (!pending.signal.aborted) setLoading(false);
    }
  };

  return (
    <div className="ground-observation-browser">
      <button
        type="button"
        aria-expanded={expanded}
        onClick={() => {
          setExpanded(!expanded);
          if (!expanded && !page && !loading) void load();
        }}
      >
        {expanded ? 'Hide' : 'Browse'} {SENSOR_LABELS[sensor]} acquisitions
      </button>
      {expanded ? (
        <section aria-label={`${SENSOR_LABELS[sensor]} acquisition catalog`}>
          <p>
            Cloud and coverage scores are advisory. Select any renderable capture for
            inspection.
          </p>
          <label>
            Selection slot
            <select
              value={role}
              onChange={(event) => setRole(event.target.value)}
              disabled={busy}
            >
              {selections.map((selection) => (
                <option key={selection.role} value={selection.role}>
                  {labelImageryRole(selection.role)}
                </option>
              ))}
            </select>
          </label>
          {page ? (
            <p>
              {page.observations.length} of {page.total} catalog acquisitions loaded.
            </p>
          ) : null}
          <ul>
            {page?.observations.map((observation) => (
              <li key={observation.observation_id}>
                <strong>{observation.product_id}</strong>
                <p>
                  {observation.platform ?? SENSOR_LABELS[sensor]} ·{' '}
                  {formatImageryTime(observation.captured_start)} →{' '}
                  {formatImageryTime(observation.captured_end)}
                </p>
                <p>Availability: {observation.readiness}</p>
                {observation.cloud_cover_fraction !== null ? (
                  <p>Cloud cover: {formatFraction(observation.cloud_cover_fraction)}</p>
                ) : null}
                {observation.quality ? (
                  <p>
                    Regional quality: {observation.quality.quality_state} · covered{' '}
                    {formatFraction(observation.quality.covered_fraction)} · usable{' '}
                    {formatFraction(observation.quality.usable_fraction)}
                  </p>
                ) : (
                  <p>Regional quality has not been assessed.</p>
                )}
                {observation.source_url?.startsWith('https://') ? (
                  <a href={observation.source_url} target="_blank" rel="noreferrer">
                    Acquisition source
                  </a>
                ) : null}
                <button
                  type="button"
                  aria-label={`Select ${observation.product_id}`}
                  disabled={
                    busy ||
                    !role ||
                    !['renderable', 'downloaded'].includes(observation.readiness)
                  }
                  onClick={() =>
                    onSelect({
                      sensor,
                      role,
                      observation_id: observation.observation_id,
                    })
                  }
                >
                  Select capture
                </button>
              </li>
            ))}
          </ul>
          {loading ? <p role="status">Loading acquisitions…</p> : null}
          {error ? <p role="alert">{error}</p> : null}
          {error || page?.next_cursor ? (
            <button type="button" disabled={loading} onClick={() => void load()}>
              {error ? 'Retry acquisitions' : 'Load more acquisitions'}
            </button>
          ) : null}
          {page && !page.total ? (
            <p>
              No acquisitions are retained for this sensor. Refresh the catalog to check
              again.
            </p>
          ) : null}
        </section>
      ) : null}
    </div>
  );
}
