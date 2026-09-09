'use client';

import { useState } from 'react';

import type { ActiveIncidentsStatus } from '@/features/incidents/hooks/useActiveIncidents';
import {
  ActiveIncident,
  ActiveIncidentsSnapshot,
  countryAssociationLabel,
  DisasterType,
  displayActiveIncidentCountry,
  displayActiveIncidentContext,
  IncidentView,
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
  search?: string;
  onSearchChange?: (value: string) => void;
  view?: IncidentView;
  onViewChange?: (value: IncidentView) => void;
  hazard?: DisasterType;
  onHazardChange?: (value: DisasterType | undefined) => void;
  onLoadMore?: () => void | Promise<void>;
  loadingMore?: boolean;
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

const VIEW_LABELS: Record<IncidentView, string> = {
  recent: 'Recent onset',
  ongoing: 'Ongoing',
  recently_updated: 'Recently updated',
  historical: 'Historical window',
};

function activityStatusLabel(status: ActiveIncident['activity_status']): string {
  switch (status) {
    case 'ongoing':
      return 'Ongoing';
    case 'ended':
      return 'Ended';
    default:
      return 'Activity unknown';
  }
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
  search,
  onSearchChange,
  view = 'recent',
  onViewChange,
  hazard,
  onHazardChange,
  onLoadMore,
  loadingMore = false,
  onSelectIncident,
  onRefresh,
}: ActiveIncidentsPanelProps) {
  const [localSearch, setLocalSearch] = useState('');
  const isServerSearch = search !== undefined;
  const currentSearch = search ?? localSearch;
  const query = currentSearch.trim().toLocaleLowerCase();
  const incidents = isServerSearch
    ? (snapshot?.incidents ?? [])
    : (snapshot?.incidents ?? []).filter((incident) =>
        [
          incident.country?.name,
          incident.country?.code,
          incident.location,
          incident.source.publisher,
          incident.source.title,
        ]
          .filter((value): value is string => Boolean(value))
          .some((value) => value.toLocaleLowerCase().includes(query)),
      );
  const updateSearch = (value: string) => {
    setLocalSearch(value);
    onSearchChange?.(value);
  };

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
          {status === 'loading'
            ? 'Updating…'
            : snapshot
              ? `Retrieved ${formatTime(snapshot.retrieved_at)}`
              : 'Not retrieved'}
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
          value={currentSearch}
          onChange={(event) => updateSearch(event.target.value)}
        />
      </div>
      <div className="incident-query-controls" aria-label="Incident filters">
        <label>
          <span>View</span>
          <select
            aria-label="Incident view"
            value={view}
            onChange={(event) => onViewChange?.(event.target.value as IncidentView)}
          >
            {Object.entries(VIEW_LABELS).map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
        </label>
        <label>
          <span>Hazard</span>
          <select
            aria-label="Hazard filter"
            value={hazard ?? ''}
            onChange={(event) =>
              onHazardChange?.(
                event.target.value ? (event.target.value as DisasterType) : undefined,
              )
            }
          >
            <option value="">All hazards</option>
            {DISASTERS.map((item) => (
              <option key={item.value} value={item.value}>
                {item.label}
              </option>
            ))}
          </select>
        </label>
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
        {snapshot && (snapshot.observations?.length ?? 0) > 0 && (
          <section
            className="incident-observations"
            aria-labelledby="incident-observations-heading"
          >
            <details>
              <summary id="incident-observations-heading">
                {snapshot.observations?.length} acquisition records excluded from
                incident counts
              </summary>
              <p>
                These are source-backed sensing or product records, not separate
                physical incidents. They remain available for provenance review.
              </p>
              <ul>
                {snapshot.observations?.slice(0, 5).map((observation) => (
                  <li key={`${observation.source.source_id}:${observation.event_id}`}>
                    {displayActiveIncidentCountry(observation)} ·{' '}
                    {observation.source.publisher}
                  </li>
                ))}
              </ul>
            </details>
          </section>
        )}
        {snapshot && (
          <section
            className="incident-list-section"
            aria-labelledby="incident-list-heading"
          >
            <div className="incident-section-heading">
              <h3 id="incident-list-heading">{VIEW_LABELS[view]}</h3>
              <span>
                {incidents.length}
                {snapshot.total_incident_count !== undefined &&
                snapshot.total_incident_count !== null &&
                snapshot.total_incident_count !== incidents.length
                  ? ` / ${snapshot.total_incident_count}`
                  : ''}
              </span>
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
                    ? isServerSearch
                      ? 'No records match your server-side search.'
                      : 'No loaded records match your search.'
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
                  const title = displayActiveIncidentCountry(incident);
                  const context = displayActiveIncidentContext(incident);
                  const provisional =
                    incident.verification_status === 'provisional_news_detected';
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
                        {provisional ? (
                          <span className="incident-provisional-status">
                            <strong>Provisional news report</strong>
                            <small>Authoritative confirmation pending</small>
                          </span>
                        ) : null}
                        {context ? (
                          <small className="incident-card-source-location">
                            {context}
                          </small>
                        ) : null}
                        {incident.geometry?.estimated && (
                          <small className="incident-geometry-estimated">
                            estimated
                          </small>
                        )}
                        <small
                          className={`incident-activity-status incident-activity-status-${incident.activity_status ?? 'unknown'}`}
                        >
                          {activityStatusLabel(incident.activity_status)}
                        </small>
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
                          <span>{countryAssociationLabel(incident)}</span>
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
                          {incident.detection?.news_break_at ? (
                            <small>
                              News first published:{' '}
                              {formatTime(incident.detection.news_break_at)}
                            </small>
                          ) : null}
                          {incident.detection?.monitor_visible_at ? (
                            <small>
                              Visible in monitoring:{' '}
                              {formatTime(incident.detection.monitor_visible_at)}
                            </small>
                          ) : null}
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
            {snapshot.has_more ? (
              <button
                className="incident-load-more"
                type="button"
                onClick={() => void onLoadMore?.()}
                disabled={loadingMore}
              >
                {loadingMore ? 'Loading more…' : 'Load more incidents'}
              </button>
            ) : null}
          </section>
        )}
      </div>
    </aside>
  );
}
