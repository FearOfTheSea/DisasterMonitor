'use client';

import { useEffect, useState, type ReactNode } from 'react';

import { formatCalendarPeriod } from '@/shared/model/calendarPeriod';

import { useGroundImageryWorkflow } from '@/features/imagery/hooks/useGroundImageryWorkflow';
import { GroundComparisons } from '@/features/imagery/ui/GroundComparisons';
import { GroundRegionPicker } from '@/features/imagery/ui/GroundRegionPicker';
import { GroundObservationBrowser } from '@/features/imagery/ui/GroundObservationBrowser';
import {
  artifactForSelection,
  formatFraction,
  formatImageryTime,
  labelImageryRole,
  labelImagerySelection,
  labelImageryState,
  roleOutcomes,
  SENSOR_LABELS,
  SENSOR_SHORT_LABELS,
  sensorStatus,
  statusClass,
  type GroundImageryPanelRequest,
} from '@/features/imagery/model/groundImagery';
import type {
  GroundImageryJobResponse,
  GroundImagerySelectionResponse,
  GroundImagerySelectionRequest,
  Sensor,
} from '@/shared/api/generated/assistant';
import { API_BASE_URL } from '@/shared/config/runtime';
import { DataAgeBadge } from '@/shared/ui/DataAgeBadge';
import { useMonitoringReadiness } from '@/shared/hooks/useMonitoringReadiness';

type GroundImageryPanelProps = {
  incidentId: string;
  incidentLabel: string;
  incidentTime: string | null;
  incidentTimePrecision?: 'exact' | 'day' | 'week' | 'range';
  incidentTimeEnd?: string | null;
  onClose: () => void;
  findOnOpen?: boolean;
  children?: ReactNode;
};

const DISPLAY_SENSORS: Sensor[] = ['sentinel-1', 'sentinel-2'];

export function GroundImageryPanel(props: GroundImageryPanelProps) {
  return <GroundImageryView key={props.incidentId} {...props} />;
}

function GroundImageryView({
  incidentId,
  incidentLabel,
  incidentTime,
  incidentTimePrecision,
  incidentTimeEnd,
  onClose,
  findOnOpen = false,
  children,
}: GroundImageryPanelProps) {
  const monitoring = useMonitoringReadiness();
  const {
    request,
    readiness,
    loadState,
    searchIsSlow,
    error,
    action,
    load,
    handleRefresh,
    handleRegion,
    handleWatch,
    handlePrepare,
    handleSelect,
  } = useGroundImageryWorkflow(
    incidentId,
    monitoring.available,
    findOnOpen,
    incidentTime !== null,
  );

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
          <p>
            {incidentTimePrecision === 'range'
              ? 'Reported event period: '
              : incidentTimePrecision === 'day'
                ? 'Reported event date: '
                : 'Event onset: '}
            {incidentTime ? (
              <time dateTime={incidentTime}>
                {incidentTimePrecision === 'range'
                  ? formatCalendarPeriod(incidentTime, incidentTimeEnd)
                  : incidentTimePrecision === 'day'
                    ? `${incidentTime.slice(0, 10)} (date only; exact time unknown)`
                    : formatImageryTime(incidentTime)}
              </time>
            ) : (
              'Event time unresolved'
            )}
          </p>
        </div>
        <button type="button" className="ground-return-button" onClick={onClose}>
          ← Return to event
        </button>
      </header>

      <div className="ground-imagery-scroll">
        <div className="ground-settings">
          {loadState === 'idle' ? (
            <div className="ground-imagery-section">
              <p>
                Search for dated radar and optical observations. A catalogue match does
                not guarantee usable imagery or a post-event view.
              </p>
              <button type="button" onClick={() => void load()}>
                Search satellite acquisitions
              </button>
            </div>
          ) : null}
          {loadState === 'loading' ? (
            <div className="ground-imagery-loading" role="status" aria-live="polite">
              <span className="loading-indicator" />
              <div>
                <strong>Searching Sentinel acquisitions</strong>
                <span>
                  Resolving event geography and checking radar and optical catalogs.
                </span>
                {searchIsSlow ? (
                  <p>
                    Copernicus Data Space is taking longer than usual. Ground view will
                    return separate partial sensor statuses if a bounded provider
                    timeout is reached.
                  </p>
                ) : null}
              </div>
            </div>
          ) : null}

          {error ? (
            <div className="ground-imagery-error" role="alert">
              <strong>{request ? 'Imagery notice' : 'Ground view unavailable'}</strong>
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
                <span
                  className={`ground-imagery-status ${statusClass(readiness.state)}`}
                >
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
              {request.reason_codes?.includes('catalog_snapshot_reused') ? (
                <p className="ground-imagery-note" role="status">
                  Recent catalog snapshot reused. Search cutoff:{' '}
                  <time
                    aria-label="Catalog snapshot cutoff"
                    dateTime={request.reference_time}
                  >
                    {formatImageryTime(request.reference_time)}
                  </time>
                  . Newer acquisitions may not be included yet.
                </p>
              ) : null}
              {request.reason_codes?.includes('artifact_cache_reused') ? (
                <p className="ground-imagery-note">
                  Previously retrieved imagery reused. Acquisition dates are shown with
                  each observation.
                </p>
              ) : null}
              {request.reason_codes?.includes('interrupted_restart') ? (
                <p role="status" className="ground-imagery-note">
                  Preparation was interrupted by a restart. Completed artifacts are
                  retained. Refresh the catalog and explicitly prepare another capture
                  to continue.
                </p>
              ) : null}
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
                {request.region.warnings
                  ?.slice(request.region.region ? 0 : 1)
                  .map((warning) => (
                    <p className="ground-imagery-note" key={warning}>
                      {warning}
                    </p>
                  ))}
                {request.region.region ? (
                  <details className="ground-region-change">
                    <summary>Choose another inspection area</summary>
                    <GroundRegionPicker
                      busy={action === 'region'}
                      onChoose={handleRegion}
                    />
                  </details>
                ) : (
                  <GroundRegionPicker
                    busy={action === 'region'}
                    onChoose={handleRegion}
                  />
                )}
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
                    <dt>Search window as of</dt>
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
                  <span
                    className={`ground-imagery-status ${statusClass(request.state)}`}
                  >
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
                    onSelect={handleSelect}
                  />
                ))}
              </section>

              {request.jobs && request.jobs.length > 0 ? (
                <section
                  className="ground-imagery-section"
                  aria-label="Ground preparation jobs"
                >
                  <div className="ground-imagery-section-heading">
                    <div>
                      <h3>Preparation jobs</h3>
                      <p>Leased work, retries, and diagnostics remain visible.</p>
                    </div>
                    <span className="ground-imagery-status is-neutral">
                      {request.jobs.length} queued or retained
                    </span>
                  </div>
                  <div className="ground-imagery-job-list">
                    {request.jobs.map((job) => (
                      <GroundPreparationJob key={job.job_id} job={job} />
                    ))}
                  </div>
                </section>
              ) : null}

              <section className="ground-imagery-actions">
                <button
                  type="button"
                  onClick={handleRefresh}
                  disabled={Boolean(action)}
                >
                  {action === 'refresh' ? 'Refreshing…' : 'Refresh catalog'}
                </button>
                <button
                  type="button"
                  onClick={handleWatch}
                  disabled={
                    Boolean(action) || (!request.watch_enabled && !monitoring.available)
                  }
                >
                  {action === 'watch'
                    ? 'Saving…'
                    : request.watch_enabled
                      ? 'Stop watching'
                      : 'Watch for new captures'}
                </button>
                {!monitoring.available ? <p>{monitoring.detail}</p> : null}
                {request.watch_enabled ? (
                  <p>Next check: {formatImageryTime(request.next_check_at)}</p>
                ) : null}
              </section>
            </>
          ) : null}

          <p className="ground-imagery-provenance">
            Request {request?.request_id ?? incidentId} · version{' '}
            {request?.request_version ?? '—'}
          </p>
        </div>
        <div className="ground-stage">
          {children ? (
            <details className="ground-imagery-section">
              <summary>Event articles and impacts</summary>
              {children}
            </details>
          ) : null}
          {request ? (
            <GroundComparisons request={request} />
          ) : (
            <section
              className="ground-imagery-section ground-imagery-comparisons"
              aria-label="Ground comparisons"
            >
              <h3>Comparison stage</h3>
              <p>
                Acquisition metadata and imagery status will appear as the event
                inspection becomes available.
              </p>
            </section>
          )}
        </div>
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
  onSelect,
}: {
  sensor: Sensor;
  request: GroundImageryPanelRequest;
  renderingReady: boolean;
  action?: string;
  onPrepare: (selection: GroundImagerySelectionResponse) => void;
  onSelect: (selection: GroundImagerySelectionRequest) => void;
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
      <GroundObservationBrowser
        key={`${request.request_id}:${request.request_version}:${sensor}`}
        requestId={request.request_id}
        sensor={sensor}
        selections={outcomes}
        busy={Boolean(action) || request.state === 'queued'}
        onSelect={onSelect}
      />
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
  const [now, setNow] = useState<number | null>(null);
  useEffect(() => {
    const initial = window.setTimeout(() => setNow(Date.now()), 0);
    const timer = window.setInterval(() => setNow(Date.now()), 60_000);
    return () => {
      window.clearTimeout(initial);
      window.clearInterval(timer);
    };
  }, []);
  return (
    <div className="ground-imagery-outcome">
      <div className="ground-imagery-outcome-heading">
        <strong>{labelImagerySelection(selection)}</strong>
        <span className={`ground-imagery-status ${statusClass(selection.reason)}`}>
          {labelImageryState(selection.reason)}
        </span>
      </div>
      {selection.observation ? (
        <>
          <p className="ground-imagery-observation-time">
            Sensed through {formatImageryTime(selection.observation.captured_end)} ·{' '}
            {selection.observation.product_id}
          </p>
          <p>
            Platform: {selection.observation.platform ?? 'Unknown'} ·{' '}
            {selection.observation.source_url?.startsWith('https://') ? (
              <a
                href={selection.observation.source_url}
                target="_blank"
                rel="noreferrer"
              >
                Acquisition source
              </a>
            ) : (
              'Acquisition source URL unavailable'
            )}
          </p>
          <DataAgeBadge
            kind="imagery_capture"
            timestamp={selection.observation.captured_end}
            ageSeconds={
              now === null
                ? undefined
                : (now - new Date(selection.observation.captured_end).getTime()) / 1000
            }
          />
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
              <>
                <a
                  href={`${API_BASE_URL}/ground-imagery/artifacts/${encodeURIComponent(artifact.artifact_id)}/download`}
                >
                  Download validated COG
                </a>
                <span className="ground-imagery-note">
                  Prepared {formatImageryTime(artifact.created_at)}
                </span>
              </>
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

function GroundPreparationJob({ job }: { job: GroundImageryJobResponse }) {
  return (
    <article className="ground-imagery-job">
      <div className="ground-imagery-outcome-heading">
        <strong>
          {job.sensor} · {labelImageryRole(job.role)}
        </strong>
        <span className={`ground-imagery-status ${statusClass(job.status)}`}>
          {labelImageryState(job.status)}
        </span>
      </div>
      <small>
        Attempt {job.attempt}/{job.max_attempts} · version {job.request_version}
      </small>
      <small>Next attempt: {formatImageryTime(job.next_attempt_at)}</small>
      {job.lease_expires_at ? (
        <small>Lease expires: {formatImageryTime(job.lease_expires_at)}</small>
      ) : null}
      {job.error_code ? <small>Error: {job.error_code}</small> : null}
      {job.diagnostic ? <p className="ground-imagery-note">{job.diagnostic}</p> : null}
    </article>
  );
}
