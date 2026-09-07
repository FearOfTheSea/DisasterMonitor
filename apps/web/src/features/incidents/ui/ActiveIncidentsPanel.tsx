'use client';

import { useState } from 'react';

import type { ActiveIncidentsStatus } from '@/features/incidents/hooks/useActiveIncidents';
import type {
  ActiveIncident,
  ActiveIncidentsSnapshot,
  DisasterType,
  IncidentSourceAuthority,
} from '@/features/incidents/model/activeIncidents';
import { IncidentCoverageStatus } from '@/features/incidents/ui/IncidentCoverageStatus';
import { DisasterIcon } from '@/features/incidents/ui/DisasterIcon';
import type { MapTimeWindow } from '@/shared/model/displayTimeWindow';

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

const GFM_WORLDWIDE_LOCATION_PREFIX = 'CEMS GFM acquisition ';

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

function formatRelativeTime(value: string, reference?: string): string {
  const eventTime = new Date(value).getTime();
  const referenceTime = reference ? new Date(reference).getTime() : Date.now();
  if (Number.isNaN(eventTime) || Number.isNaN(referenceTime)) return formatTime(value);
  const minutes = Math.max(0, Math.round((referenceTime - eventTime) / 60_000));
  if (minutes < 60) return minutes < 5 ? 'Reported recently' : `${minutes} min ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours} ${hours === 1 ? 'hour' : 'hours'} ago`;
  const days = Math.round(hours / 24);
  return `${days} ${days === 1 ? 'day' : 'days'} ago`;
}

function formatDuration(seconds: number): string {
  if (seconds < 3_600) return 'less than 1 hour';
  const hours = Math.round(seconds / 3_600);
  return `${hours} ${hours === 1 ? 'hour' : 'hours'}`;
}

function disasterLabel(disaster: DisasterType): string {
  return DISASTERS.find((item) => item.value === disaster)?.label ?? disaster;
}

function incidentTitle(incident: ActiveIncident): string {
  if (
    incident.source.source_id === 'cems-gfm-floods' &&
    incident.location.startsWith(GFM_WORLDWIDE_LOCATION_PREFIX)
  ) {
    return 'Worldwide';
  }
  return incident.location;
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
  const [search, setSearch] = useState('');
  const query = search.trim().toLocaleLowerCase();
  const incidents = [...(snapshot?.incidents ?? [])]
    .filter((incident) =>
      [incident.location, incident.source.publisher, incident.source.title].some(
        (value) => value.toLocaleLowerCase().includes(query),
      ),
    )
    .sort((first, second) => {
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
          <h2>What&apos;s happening</h2>
          <p>Recent events reported by trusted sources</p>
        </div>
        <button
          type="button"
          onClick={() => void onRefresh()}
          disabled={status === 'loading'}
        >
          {status === 'loading' ? 'Updating…' : 'Updated just now'}
        </button>
      </header>
      <div className="incident-search">
        <svg
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.7"
          aria-hidden="true"
        >
          <circle cx="10.5" cy="10.5" r="6.5" />
          <path d="m16 16 4.5 4.5" />
        </svg>
        <input
          type="search"
          aria-label="Search locations or sources"
          placeholder="Search a place or event"
          value={search}
          onChange={(event) => setSearch(event.target.value)}
        />
      </div>
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
              <h3 id="incident-list-heading">Recent events</h3>
              <span>{incidents.length}</span>
            </div>
            {displayTimeWindow && displayTimeWindow !== '7d' ? (
              <p className="incident-display-filter-note">
                Showing records in the {displayTimeWindow} display window. Provider
                coverage above is unchanged.
              </p>
            ) : null}
            {incidents.length === 0 ? (
              <div className="incident-empty">
                <strong>
                  {query
                    ? 'No loaded records match your search.'
                    : 'No incident records matched this bounded retrieval.'}
                </strong>
                <p>
                  A successful empty result does not prove that no disaster occurred.
                </p>
              </div>
            ) : (
              <div className="incident-list">
                {incidents.map((incident) => {
                  const timestamp = sourceTimestamp(incident);
                  const title = incidentTitle(incident);
                  return (
                    <article
                      key={`${incident.disaster}:${incident.event_id}`}
                      className={`incident-card incident-card-${incident.disaster}${selectedIncidentId === incident.event_id ? ' incident-card-selected' : ''}`}
                    >
                      <button
                        type="button"
                        aria-label={`Focus ${title} on map`}
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
                        <strong className="incident-card-location">{title}</strong>
                        {incident.geometry?.estimated && (
                          <small className="incident-geometry-estimated">
                            estimated
                          </small>
                        )}
                        <time dateTime={incident.event_time}>
                          {formatRelativeTime(
                            incident.event_time,
                            snapshot.retrieved_at,
                          )}
                        </time>
                      </button>
                      <details className="incident-details">
                        <summary>Source details</summary>
                        <div className="incident-metadata">
                          <span>
                            {incident.provider_tier === 'primary'
                              ? 'Primary tier'
                              : 'Secondary tier'}
                          </span>
                          <span>{AUTHORITY_LABELS[incident.source_authority]}</span>
                        </div>
                        <div className="incident-source">
                          <small className="incident-event-id">
                            Event ID: {incident.event_id}
                          </small>
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
                      </details>
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
