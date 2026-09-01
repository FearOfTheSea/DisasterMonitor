'use client';

import type { ActiveIncidentsStatus } from '@/features/incidents/hooks/useActiveIncidents';
import type {
  ActiveIncident,
  ActiveIncidentsSnapshot,
  DisasterType,
  IncidentSourceAuthority,
} from '@/features/incidents/model/activeIncidents';
import { IncidentCoverageStatus } from '@/features/incidents/ui/IncidentCoverageStatus';
import type { MapTimeWindow } from '@/features/map/model/mapLayerState';

type ActiveIncidentsPanelProps = {
  snapshot?: ActiveIncidentsSnapshot;
  coverageSnapshot?: ActiveIncidentsSnapshot;
  status: ActiveIncidentsStatus;
  error?: string;
  selectedIncidentId?: string;
  displayTimeWindow?: MapTimeWindow;
  onSelectIncident: (eventId: string) => void;
  onRefresh: () => void | Promise<void>;
};

const DISASTERS: { value: DisasterType; label: string }[] = [
  { value: 'earthquake', label: 'Earthquake' },
  { value: 'flood', label: 'Flood' },
  { value: 'wildfire', label: 'Wildfire' },
  { value: 'landslide', label: 'Landslide' },
  { value: 'tropical_cyclone', label: 'Tropical cyclone' },
  { value: 'volcanic_eruption', label: 'Volcanic eruption' },
];

const AUTHORITY_LABELS: Record<IncidentSourceAuthority, string> = {
  national_authority: 'National authority',
  scientific_authority: 'Scientific authority',
  humanitarian_aggregator: 'Humanitarian aggregator',
  secondary: 'Secondary authority',
};

function DisasterIcon({ disaster }: { disaster: DisasterType }) {
  return (
    <svg
      className={`disaster-icon disaster-icon-${disaster}`}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      {disaster === 'earthquake' && (
        <path d="M2.5 13h4l1.8-6 3.4 11 2.3-8 1.8 3H21.5" />
      )}
      {disaster === 'flood' && (
        <>
          <path d="M2.5 8.5c2.3-2 4.7-2 7 0s4.7 2 7 0 4.7-2 7 0" />
          <path d="M2.5 14.5c2.3-2 4.7-2 7 0s4.7 2 7 0 4.7-2 7 0" />
          <path d="M2.5 20c2.3-2 4.7-2 7 0s4.7 2 7 0 4.7-2 7 0" />
        </>
      )}
      {disaster === 'wildfire' && (
        <path d="M13.5 2.5c.7 4-2.8 5.2-1.7 8.3.7-1.2 1.9-2 3.3-2.4 2.6 2.3 4 4.6 3.5 7.2-.6 3.3-3.3 5.9-6.8 5.9s-6.4-2.7-6.4-6.2c0-2.7 1.5-5 4.6-7.1-.2 2.1.4 3.5 1.6 4.2-.2-3.5.6-6.8 1.9-9.9Z" />
      )}
      {disaster === 'landslide' && (
        <>
          <path d="m2.5 19 6.7-12 4.1 7 2.1-3.5L21.5 19Z" />
          <path d="m12.2 8.2 1.8-3M15.4 8.4l2.5-1M16.6 11.2l2.8.2" />
        </>
      )}
      {disaster === 'tropical_cyclone' && (
        <>
          <path d="M19.8 7.5A8.3 8.3 0 0 0 5 8c1.7-1 4.3-1.2 6.2.3 1 .8 1.5 2.2 1.2 3.5" />
          <path d="M4.2 16.5A8.3 8.3 0 0 0 19 16c-1.7 1-4.3 1.2-6.2-.3-1-.8-1.5-2.2-1.2-3.5" />
          <circle cx="12" cy="12" r="1.5" />
        </>
      )}
      {disaster === 'volcanic_eruption' && (
        <>
          <path d="m4 20 5.6-11h4.8L20 20Z" />
          <path d="m9.6 9 2.4 3 2.4-3M8.5 5.5 7 3.5M12 5V2M15.5 5.5 17 3.5" />
        </>
      )}
    </svg>
  );
}

function SelectedIcon() {
  return (
    <svg viewBox="0 0 16 16" aria-hidden="true">
      <circle cx="8" cy="8" r="7" />
      <path d="m4.5 8.1 2.1 2.1 4.9-4.9" />
    </svg>
  );
}

function ChevronIcon() {
  return (
    <svg viewBox="0 0 16 16" aria-hidden="true">
      <path d="m6 3 5 5-5 5" />
    </svg>
  );
}

function formatTime(value: string): string {
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleString();
}

function formatDuration(seconds: number): string {
  if (seconds < 3_600) return 'less than 1 hour';
  const hours = Math.round(seconds / 3_600);
  return `${hours} ${hours === 1 ? 'hour' : 'hours'}`;
}

function disasterLabel(disaster: DisasterType): string {
  return DISASTERS.find((item) => item.value === disaster)?.label ?? disaster;
}

function sourceTimestamp(incident: ActiveIncident): { label: string; value: string } {
  if (incident.source.updated_at) {
    return { label: 'Source updated', value: incident.source.updated_at };
  }
  if (incident.source.published_at) {
    return { label: 'Source published', value: incident.source.published_at };
  }
  return { label: 'Source retrieved', value: incident.source.retrieved_at };
}

export function ActiveIncidentsPanel({
  snapshot,
  coverageSnapshot,
  status,
  error,
  selectedIncidentId,
  displayTimeWindow,
  onSelectIncident,
  onRefresh,
}: ActiveIncidentsPanelProps) {
  const incidents = [...(snapshot?.incidents ?? [])].sort((first, second) => {
    const timeDifference =
      new Date(second.event_time).getTime() - new Date(first.event_time).getTime();
    return (
      timeDifference ||
      first.disaster.localeCompare(second.disaster) ||
      first.event_id.localeCompare(second.event_id)
    );
  });

  return (
    <aside className="active-incidents-panel" aria-label="Active incidents monitoring">
      <header className="active-incidents-header">
        <div>
          <h2>Active incidents</h2>
          <p>Bounded worldwide event discovery from configured providers.</p>
        </div>
        <button
          type="button"
          onClick={() => void onRefresh()}
          disabled={status === 'loading'}
        >
          {status === 'loading' ? 'Refreshing…' : 'Refresh'}
        </button>
      </header>
      <div className="active-incidents-scroll">
        {status === 'loading' && !snapshot && (
          <div className="incident-loading" role="status">
            <span className="loading-indicator" aria-hidden="true" />
            <span>Loading active incidents…</span>
          </div>
        )}
        {error && (
          <div className="incident-error" role="alert">
            {snapshot ? 'Refresh failed: ' : ''}
            {error}
          </div>
        )}
        {snapshot ? (
          <IncidentCoverageStatus snapshot={coverageSnapshot ?? snapshot} />
        ) : null}
        {snapshot && (snapshot.correlations?.length ?? 0) > 0 && (
          <section
            className="incident-correlations"
            aria-labelledby="incident-correlations-heading"
          >
            <div className="incident-section-heading">
              <h3 id="incident-correlations-heading">Related hazard context</h3>
              <span>{snapshot.correlations?.length}</span>
            </div>
            <p>
              Rule-bounded proximity between distinct records. These are descriptive
              associations, not merged incidents.
            </p>
            <div className="incident-correlation-list">
              {snapshot.correlations?.map((correlation) => (
                <article key={correlation.correlation_id}>
                  <strong>
                    {disasterLabel(correlation.first_disaster)} →{' '}
                    {disasterLabel(correlation.second_disaster)}
                  </strong>
                  <p>{correlation.summary}</p>
                  <dl>
                    <div>
                      <dt>Approx. distance</dt>
                      <dd>{correlation.distance_km.toLocaleString()} km</dd>
                    </div>
                    <div>
                      <dt>Time apart</dt>
                      <dd>{formatDuration(correlation.time_delta_seconds)}</dd>
                    </div>
                  </dl>
                  <small>Sources: {correlation.source_ids.join(', ')}</small>
                  <small className="incident-correlation-limitation">
                    {correlation.limitation}
                  </small>
                </article>
              ))}
            </div>
          </section>
        )}
        {snapshot && (
          <section
            className="incident-list-section"
            aria-labelledby="incident-list-heading"
          >
            <div className="incident-section-heading">
              <h3 id="incident-list-heading">Recent source records</h3>
              <span>{incidents.length}</span>
            </div>
            {displayTimeWindow ? (
              <p className="incident-display-filter-note">
                Showing records in the {displayTimeWindow} display window. Provider
                coverage above is unchanged.
              </p>
            ) : null}
            {incidents.length === 0 ? (
              <div className="incident-empty">
                <strong>No incident records matched this bounded retrieval.</strong>
                <p>
                  A successful empty result does not prove that no disaster occurred.
                </p>
              </div>
            ) : (
              <div className="incident-list">
                {incidents.map((incident) => {
                  const timestamp = sourceTimestamp(incident);
                  return (
                    <article
                      key={`${incident.disaster}:${incident.event_id}`}
                      className={`incident-card incident-card-${incident.disaster}${selectedIncidentId === incident.event_id ? ' incident-card-selected' : ''}`}
                    >
                      <button
                        type="button"
                        aria-label={`Focus ${incident.location} on map`}
                        aria-pressed={selectedIncidentId === incident.event_id}
                        onClick={() => onSelectIncident(incident.event_id)}
                      >
                        <span className="incident-card-heading">
                          <span className="incident-disaster-label">
                            <DisasterIcon disaster={incident.disaster} />
                            {disasterLabel(incident.disaster)}
                          </span>
                          {selectedIncidentId === incident.event_id && (
                            <span className="incident-selected-label">
                              <SelectedIcon />
                              Selected
                            </span>
                          )}
                          <span className="incident-chevron">
                            <ChevronIcon />
                          </span>
                        </span>
                        <strong>{incident.location}</strong>
                        {incident.geometry?.estimated && (
                          <small className="incident-geometry-estimated">
                            estimated
                          </small>
                        )}
                        <time dateTime={incident.event_time}>
                          {formatTime(incident.event_time)}
                        </time>
                      </button>
                      <div className="incident-metadata">
                        <span>
                          {incident.provider_tier === 'primary'
                            ? 'Primary tier'
                            : 'Secondary tier'}
                        </span>
                        <span>{AUTHORITY_LABELS[incident.source_authority]}</span>
                      </div>
                      <div className="incident-source">
                        <span>{incident.source.publisher}</span>
                        <a
                          href={incident.source.canonical_url}
                          target="_blank"
                          rel="noreferrer"
                        >
                          {incident.source.title}
                        </a>
                        <small>
                          {timestamp.label}: {formatTime(timestamp.value)}
                        </small>
                      </div>
                      {incident.geometry?.kind === 'descriptive' && (
                        <small className="incident-geometry-note">
                          Descriptive location only; no map geometry was supplied.
                        </small>
                      )}
                    </article>
                  );
                })}
              </div>
            )}
          </section>
        )}
      </div>
    </aside>
  );
}
