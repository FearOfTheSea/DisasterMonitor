'use client';

import type { ActiveIncidentsStatus } from '@/features/incidents/hooks/useActiveIncidents';
import type {
  ActiveIncident,
  ActiveIncidentsSnapshot,
  DisasterIncidentCoverage,
  DisasterType,
  IncidentCoverageState,
  IncidentSourceAuthority,
} from '@/features/incidents/model/activeIncidents';

type ActiveIncidentsPanelProps = {
  snapshot?: ActiveIncidentsSnapshot;
  status: ActiveIncidentsStatus;
  error?: string;
  selectedIncidentId?: string;
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

const COVERAGE_LABELS: Record<IncidentCoverageState, string> = {
  events_found: 'Events found',
  no_matching_records: 'No matching records',
  degraded: 'Degraded',
  unavailable: 'Unavailable',
};

const AUTHORITY_LABELS: Record<IncidentSourceAuthority, string> = {
  national_authority: 'National authority',
  scientific_authority: 'Scientific authority',
  humanitarian_aggregator: 'Humanitarian aggregator',
  secondary: 'Secondary authority',
};

function formatTime(value: string): string {
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleString();
}

function coverageFor(
  snapshot: ActiveIncidentsSnapshot,
  disaster: DisasterType,
): DisasterIncidentCoverage {
  return (
    snapshot.coverage.find((item) => item.disaster === disaster) ?? {
      disaster,
      state: 'unavailable',
      incident_count: 0,
      providers: [],
      detail: 'The API returned no coverage result for this disaster.',
    }
  );
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
  status,
  error,
  selectedIncidentId,
  onSelectIncident,
  onRefresh,
}: ActiveIncidentsPanelProps) {
  const partial = snapshot?.coverage.some(
    (item) => item.state === 'degraded' || item.state === 'unavailable',
  );
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
        {snapshot && (
          <p className="incident-retrieval-time">
            Retrieved:{' '}
            <time dateTime={snapshot.retrieved_at}>
              {formatTime(snapshot.retrieved_at)}
            </time>
          </p>
        )}
        {status === 'loading' && !snapshot && (
          <p role="status">Loading active incidents…</p>
        )}
        {error && (
          <div className="incident-error" role="alert">
            {snapshot ? 'Refresh failed: ' : ''}
            {error}
          </div>
        )}
        {snapshot && (
          <section
            className="incident-coverage-section"
            aria-labelledby="coverage-heading"
          >
            <div className="incident-section-heading">
              <h3 id="coverage-heading">Provider coverage</h3>
              {partial && <span className="incident-partial">Coverage is partial</span>}
            </div>
            <div className="incident-coverage-grid">
              {DISASTERS.map((definition) => {
                const coverage = coverageFor(snapshot, definition.value);
                return (
                  <article key={definition.value} data-testid="incident-coverage">
                    <div>
                      <strong>{definition.label}</strong>
                      <span className={`coverage-state coverage-${coverage.state}`}>
                        {COVERAGE_LABELS[coverage.state]}
                      </span>
                    </div>
                    <small>{coverage.detail}</small>
                  </article>
                );
              })}
            </div>
          </section>
        )}
        {snapshot && snapshot.warnings.length > 0 && (
          <section
            className="incident-warnings"
            aria-labelledby="incident-warnings-heading"
          >
            <h3 id="incident-warnings-heading">Retrieval warnings</h3>
            <p>
              Provider notices describe coverage limits; they are not disaster claims.
            </p>
            <ul>
              {snapshot.warnings.map((warning) => (
                <li key={warning}>{warning}</li>
              ))}
            </ul>
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
                      className={
                        selectedIncidentId === incident.event_id
                          ? 'incident-card incident-card-selected'
                          : 'incident-card'
                      }
                    >
                      <button
                        type="button"
                        aria-label={`Focus ${incident.location} on map`}
                        aria-pressed={selectedIncidentId === incident.event_id}
                        onClick={() => onSelectIncident(incident.event_id)}
                      >
                        <span>{disasterLabel(incident.disaster)}</span>
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
