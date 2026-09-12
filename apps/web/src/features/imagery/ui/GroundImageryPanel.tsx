'use client';

import { useCallback, useEffect, useState } from 'react';

import {
  createGroundImageryRequest,
  fetchGroundImageryReadiness,
  prepareGroundImagerySelection,
  refreshGroundImageryRequest,
  setGroundImageryWatch,
} from '@/features/imagery/api/groundImageryClient';
import {
  artifactForSelection,
  formatFraction,
  formatImageryTime,
  labelImageryRole,
  labelImageryState,
  roleOutcomes,
  SENSOR_LABELS,
  SENSOR_SHORT_LABELS,
  sensorStatus,
  statusClass,
  type GroundImageryPanelReadiness,
  type GroundImageryPanelRequest,
} from '@/features/imagery/model/groundImagery';
import type {
  GroundImagerySelectionResponse,
  Sensor,
} from '@/shared/api/generated/assistant';
import { API_BASE_URL } from '@/shared/config/runtime';

type GroundImageryPanelProps = {
  incidentId: string;
  incidentLabel: string;
  onClose: () => void;
};

type LoadState = 'idle' | 'loading' | 'ready' | 'error';

const DISPLAY_SENSORS: Sensor[] = ['sentinel-1', 'sentinel-2'];

export function GroundImageryPanel({
  incidentId,
  incidentLabel,
  onClose,
}: GroundImageryPanelProps) {
  const [request, setRequest] = useState<GroundImageryPanelRequest>();
  const [readiness, setReadiness] = useState<GroundImageryPanelReadiness>();
  const [loadState, setLoadState] = useState<LoadState>('idle');
  const [error, setError] = useState<string>();
  const [action, setAction] = useState<string>();

  const load = useCallback(
    async (signal?: AbortSignal) => {
      setLoadState('loading');
      setError(undefined);
      try {
        const [nextReadiness, nextRequest] = await Promise.all([
          fetchGroundImageryReadiness(signal),
          createGroundImageryRequest(incidentId, signal),
        ]);
        setReadiness(nextReadiness);
        setRequest(nextRequest);
        setLoadState('ready');
      } catch (loadError) {
        if (loadError instanceof DOMException && loadError.name === 'AbortError') {
          return;
        }
        setError(
          loadError instanceof Error ? loadError.message : 'Ground view failed.',
        );
        setLoadState('error');
      }
    },
    [incidentId],
  );

  useEffect(() => {
    const controller = new AbortController();
    const timer = window.setTimeout(() => void load(controller.signal), 0);
    return () => {
      window.clearTimeout(timer);
      controller.abort();
    };
  }, [load]);

  const runAction = useCallback(
    async (name: string, operation: () => Promise<GroundImageryPanelRequest>) => {
      setAction(name);
      setError(undefined);
      try {
        setRequest(await operation());
      } catch (actionError) {
        setError(
          actionError instanceof Error
            ? actionError.message
            : 'Ground view action failed.',
        );
      } finally {
        setAction(undefined);
      }
    },
    [],
  );

  const handleRefresh = () => {
    if (!request) return;
    void runAction('refresh', () => refreshGroundImageryRequest(request.request_id));
  };

  const handleWatch = () => {
    if (!request) return;
    void runAction('watch', () =>
      setGroundImageryWatch(request.request_id, !request.watch_enabled),
    );
  };

  const handlePrepare = (selection: GroundImagerySelectionResponse) => {
    if (!request || !selection.observation) return;
    void runAction(`prepare:${selection.selection_id}`, () =>
      prepareGroundImagerySelection(request.request_id, {
        sensor: selection.sensor,
        role: selection.role,
        overview: true,
      }),
    );
  };

  return (
    <aside
      id="ground-imagery-panel"
      className="ground-imagery-panel"
      aria-labelledby="ground-imagery-heading"
    >
      <header className="ground-imagery-panel-header">
        <div>
          <span className="ground-imagery-kicker">Event-focused inspection</span>
          <h2 id="ground-imagery-heading">Ground view</h2>
          <p>{incidentLabel}</p>
        </div>
        <button
          className="panel-close"
          type="button"
          onClick={onClose}
          aria-label="Close Ground view"
        >
          <svg viewBox="0 0 24 24" aria-hidden="true">
            <path d="m6 6 12 12M18 6 6 18" />
          </svg>
        </button>
      </header>

      <div className="ground-imagery-scroll">
        {loadState === 'loading' ? (
          <div className="ground-imagery-loading" role="status" aria-live="polite">
            <span className="loading-indicator" />
            <span>Resolving event geography and searching Sentinel acquisitions…</span>
          </div>
        ) : null}

        {error ? (
          <div className="ground-imagery-error" role="alert">
            <strong>Ground view unavailable</strong>
            <p>{error}</p>
            <button type="button" onClick={() => void load()}>
              Try again
            </button>
          </div>
        ) : null}

        {readiness ? (
          <section className="ground-imagery-section ground-imagery-readiness">
            <div className="ground-imagery-section-heading">
              <div>
                <h3>Availability</h3>
                <p>{readiness.detail}</p>
              </div>
              <span className={`ground-imagery-status ${statusClass(readiness.state)}`}>
                {labelImageryState(readiness.state)}
              </span>
            </div>
            {readiness.state === 'credentials_required' ? (
              <p className="ground-imagery-note">
                Catalog discovery is public. Rendering a validated COG requires the
                server’s CDSE processing credentials.
              </p>
            ) : null}
          </section>
        ) : null}

        {request ? (
          <>
            <section className="ground-imagery-section">
              <div className="ground-imagery-section-heading">
                <div>
                  <h3>Region basis</h3>
                  <p>Impact geography is separate from the satellite footprint.</p>
                </div>
                <span
                  className={`ground-imagery-status ${statusClass(request.region.state)}`}
                >
                  {labelImageryState(request.region.state)}
                </span>
              </div>
              {request.region.region ? (
                <dl className="ground-imagery-facts">
                  <div>
                    <dt>Association</dt>
                    <dd>{request.region.region.association.replaceAll('_', ' ')}</dd>
                  </div>
                  <div>
                    <dt>Region version</dt>
                    <dd>
                      {request.region.region.region_id} · v
                      {request.region.region.version}
                    </dd>
                  </div>
                  <div>
                    <dt>Source evidence</dt>
                    <dd>
                      {request.region.region.source_footprints.length > 0
                        ? request.region.region.source_footprints
                            .map((item) => String(item.source_kind ?? 'source'))
                            .join(', ')
                        : 'Not recorded'}
                    </dd>
                  </div>
                </dl>
              ) : (
                <div className="ground-imagery-empty">
                  <strong>Choose an inspection region</strong>
                  <p>
                    {request.region.warnings?.[0] ??
                      'There is not enough defensible event geography to search imagery.'}
                  </p>
                </div>
              )}
              {request.region.warnings?.slice(1).map((warning) => (
                <p className="ground-imagery-note" key={warning}>
                  {warning}
                </p>
              ))}
            </section>

            <section className="ground-imagery-section">
              <div className="ground-imagery-section-heading">
                <div>
                  <h3>Temporal basis</h3>
                  <p>Exact sensing times remain visible beside operator labels.</p>
                </div>
                <span className="ground-imagery-status is-neutral">
                  {request.temporal_plan.onset_precision
                    ? request.temporal_plan.onset_precision.replaceAll('_', ' ')
                    : 'Onset unknown'}
                </span>
              </div>
              <dl className="ground-imagery-facts">
                <div>
                  <dt>Reference</dt>
                  <dd>{formatImageryTime(request.temporal_plan.reference_time)}</dd>
                </div>
                <div>
                  <dt>Impact onset</dt>
                  <dd>
                    {request.temporal_plan.impact_start_earliest
                      ? `${formatImageryTime(request.temporal_plan.impact_start_earliest)} → ${formatImageryTime(request.temporal_plan.impact_start_latest)}`
                      : 'Unknown; roles are not labelled before or after impact.'}
                  </dd>
                </div>
              </dl>
            </section>

            <section className="ground-imagery-section ground-imagery-sensors">
              <div className="ground-imagery-section-heading">
                <div>
                  <h3>Independent sensor views</h3>
                  <p>Radar and optical availability are assessed separately.</p>
                </div>
                <span className={`ground-imagery-status ${statusClass(request.state)}`}>
                  {labelImageryState(request.state)}
                </span>
              </div>
              {DISPLAY_SENSORS.map((sensor) => (
                <SensorCard
                  key={sensor}
                  sensor={sensor}
                  request={request}
                  renderingReady={readiness?.state === 'ready'}
                  action={action}
                  onPrepare={handlePrepare}
                />
              ))}
            </section>

            <section className="ground-imagery-actions">
              <button type="button" onClick={handleRefresh} disabled={Boolean(action)}>
                {action === 'refresh' ? 'Refreshing…' : 'Refresh catalog'}
              </button>
              <button type="button" onClick={handleWatch} disabled={Boolean(action)}>
                {action === 'watch'
                  ? 'Saving…'
                  : request.watch_enabled
                    ? 'Stop watching'
                    : 'Watch for new captures'}
              </button>
              {request.watch_enabled ? (
                <p>Next check: {formatImageryTime(request.next_check_at)}</p>
              ) : null}
            </section>
          </>
        ) : null}

        <p className="ground-imagery-provenance">
          Request {request?.request_id ?? incidentId} · version{' '}
          {request?.request_version ?? '—'}
          {request
            ? ` · reference ${formatImageryTime(request.temporal_plan.reference_time)}`
            : ''}
        </p>
      </div>
    </aside>
  );
}

function SensorCard({
  sensor,
  request,
  renderingReady,
  action,
  onPrepare,
}: {
  sensor: Sensor;
  request: GroundImageryPanelRequest;
  renderingReady: boolean;
  action?: string;
  onPrepare: (selection: GroundImagerySelectionResponse) => void;
}) {
  const status = sensorStatus(request, sensor);
  const outcomes = roleOutcomes(status);
  return (
    <article className="ground-imagery-sensor-card">
      <header>
        <div>
          <span className="ground-imagery-sensor-code">
            {SENSOR_SHORT_LABELS[sensor]}
          </span>
          <div>
            <h4>{SENSOR_LABELS[sensor]}</h4>
            <p>
              {status?.scanned_count ?? 0} acquisitions scanned ·{' '}
              {status?.scan_complete ? 'scan complete' : 'scan bounded or incomplete'}
            </p>
          </div>
        </div>
        <span
          className={`ground-imagery-status ${statusClass(status?.failure_code ?? 'neutral')}`}
        >
          {status?.failure_code ? labelImageryState(status.failure_code) : 'Available'}
        </span>
      </header>
      <div className="ground-imagery-outcomes">
        {outcomes.length === 0 ? (
          <p className="ground-imagery-note">No role outcomes were returned.</p>
        ) : (
          outcomes.map((selection) => (
            <SelectionOutcome
              key={selection.selection_id}
              selection={selection}
              artifact={artifactForSelection(request.artifacts, selection.selection_id)}
              renderingReady={renderingReady}
              action={action}
              onPrepare={onPrepare}
            />
          ))
        )}
      </div>
    </article>
  );
}

function SelectionOutcome({
  selection,
  artifact,
  renderingReady,
  action,
  onPrepare,
}: {
  selection: GroundImagerySelectionResponse;
  artifact?: NonNullable<GroundImageryPanelRequest['artifacts']>[number];
  renderingReady: boolean;
  action?: string;
  onPrepare: (selection: GroundImagerySelectionResponse) => void;
}) {
  return (
    <div className="ground-imagery-outcome">
      <div className="ground-imagery-outcome-heading">
        <strong>{labelImageryRole(selection.role)}</strong>
        <span className={`ground-imagery-status ${statusClass(selection.reason)}`}>
          {labelImageryState(selection.reason)}
        </span>
      </div>
      {selection.observation ? (
        <>
          <p className="ground-imagery-observation-time">
            Sensed {formatImageryTime(selection.observation.captured_start)} ·{' '}
            {selection.observation.product_id}
          </p>
          {selection.observation.quality ? (
            <p className="ground-imagery-quality">
              Core usable{' '}
              {formatFraction(selection.observation.quality.usable_fraction)} · covered{' '}
              {formatFraction(selection.observation.quality.covered_fraction)}
            </p>
          ) : (
            <p className="ground-imagery-note">
              Quality masks are not assessed for this catalogue result.
            </p>
          )}
          <div className="ground-imagery-outcome-actions">
            {artifact ? (
              <a
                href={`${API_BASE_URL}/ground-imagery/artifacts/${encodeURIComponent(artifact.artifact_id)}/download`}
              >
                Download validated COG
              </a>
            ) : renderingReady ? (
              <button
                type="button"
                onClick={() => onPrepare(selection)}
                disabled={Boolean(action)}
              >
                {action === `prepare:${selection.selection_id}`
                  ? 'Preparing…'
                  : 'Prepare COG'}
              </button>
            ) : (
              <span className="ground-imagery-note">
                Rendering credentials required
              </span>
            )}
            <a
              href={`${API_BASE_URL}/ground-imagery/selections/${encodeURIComponent(selection.selection_id)}/manifest`}
            >
              Manifest
            </a>
          </div>
        </>
      ) : null}
      <p className="ground-imagery-explanation">{selection.explanation}</p>
    </div>
  );
}
