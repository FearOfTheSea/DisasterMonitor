'use client';

import { useState, type ReactNode } from 'react';

import type { ActiveIncidentsStatus } from '@/features/incidents/hooks/useActiveIncidents';
import {
  ActiveIncident,
  ActiveIncidentsSnapshot,
  countryAssociationLabel,
  DisasterType,
  displayActiveIncidentCountry,
  displayActiveIncidentContext,
  IncidentView,
  isContextOnlyIncident,
} from '@/features/incidents/model/activeIncidents';
import { AccessibleIncidentIndex } from '@/features/incidents/ui/AccessibleIncidentIndex';
import { IncidentCoverageStatus } from '@/features/incidents/ui/IncidentCoverageStatus';
import { DisasterIcon } from '@/features/incidents/ui/DisasterIcon';
import { IncidentPanelControls } from '@/features/incidents/ui/IncidentPanelControls';
import {
  activityStatusLabel,
  AUTHORITY_LABELS,
  disasterLabel,
  incidentDateOnly,
} from '@/features/incidents/ui/incidentPresentation';
import type { MapTimeWindow } from '@/shared/model/displayTimeWindow';
import { DataAgeBadge } from '@/shared/ui/DataAgeBadge';

type ActiveIncidentsPanelProps = {
  discoveryControls?: ReactNode;
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
  occurrenceStart?: string;
  occurrenceEnd?: string;
  onOccurrenceStartChange?: (value: string) => void;
  onOccurrenceEndChange?: (value: string) => void;
  onLoadMore?: () => void | Promise<void>;
  loadingMore?: boolean;
  onSelectIncident: (eventId: string) => void;
  onRefresh: () => void | Promise<void>;
  compact?: boolean;
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

function formatTime(value: string | null): string {
  if (!value) return 'Unknown';
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleString();
}

function formatRelativeTime(value: string | null, reference?: string): string {
  if (!value) return 'Unknown';
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

function formatObservationPeriod(observation: ActiveIncident): string {
  if (!observation.event_time) return 'Event time unknown';
  if (observation.event_time_precision !== 'week' || !observation.event_time_end) {
    return formatTime(observation.event_time);
  }

  const start = new Date(observation.event_time);
  const end = new Date(observation.event_time_end);
  if (Number.isNaN(start.getTime()) || Number.isNaN(end.getTime())) {
    return `${observation.event_time}–${observation.event_time_end}`;
  }

  const startLabel = start.toLocaleDateString('en-US', {
    month: 'short',
    day: 'numeric',
    timeZone: 'UTC',
  });
  const endLabel = end.toLocaleDateString('en-US', {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
    timeZone: 'UTC',
  });
  return `Week of ${startLabel}–${endLabel}`;
}

function observationKindLabel(observation: ActiveIncident): string {
  return observation.observation_kind === 'preliminary_event'
    ? 'Preliminary event report'
    : 'Acquisition record';
}

const VIEW_LABELS: Record<IncidentView, string> = {
  recent: 'Recent onset',
  ongoing: 'Ongoing',
  recently_updated: 'Recently updated',
  historical: 'Historical window',
};

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
  discoveryControls,
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
  occurrenceStart = '',
  occurrenceEnd = '',
  onOccurrenceStartChange,
  onOccurrenceEndChange,
  onLoadMore,
  loadingMore = false,
  onSelectIncident,
  onRefresh,
  compact = false,
}: ActiveIncidentsPanelProps) {
  const [localSearch, setLocalSearch] = useState('');
  const [contextLimit, setContextLimit] = useState(20);
  const isServerSearch = search !== undefined;
  const currentSearch = search ?? localSearch;
  const query = currentSearch.trim().toLocaleLowerCase();
  const matching = isServerSearch
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
  const incidents = matching.filter((incident) => !isContextOnlyIncident(incident));
  const context = matching.filter(isContextOnlyIncident);
  const updateSearch = (value: string) => {
    setLocalSearch(value);
    onSearchChange?.(value);
  };

  return (
    <aside className="active-incidents-panel" aria-label="Active incidents monitoring">
      <header className="active-incidents-header">
        <div>
          <h2>{compact ? 'Explore the world' : "What's happening"}</h2>
          <p>
            {compact
              ? 'Recent events, grounded in sources.'
              : 'Recent events reported by trusted sources'}
          </p>
        </div>
      </header>
      {discoveryControls}
      {snapshot?.publication_scan ? (
        <div className="incident-query-controls">
          <label>
            Search scan results
            <input
              type="search"
              aria-label="Search scan results"
              value={currentSearch}
              onChange={(event) => updateSearch(event.target.value)}
            />
          </label>
          <label>
            Hazard
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
              {[
                'earthquake',
                'flood',
                'wildfire',
                'landslide',
                'drought',
                'tropical_cyclone',
                'volcanic_eruption',
              ].map((value) => (
                <option key={value} value={value}>
                  {disasterLabel(value as DisasterType)}
                </option>
              ))}
            </select>
          </label>
        </div>
      ) : (
        <IncidentPanelControls
          snapshot={snapshot}
          status={status}
          error={error}
          search={currentSearch}
          serverSearch={isServerSearch}
          onSearchChange={updateSearch}
          view={view}
          onViewChange={onViewChange}
          hazard={hazard}
          onHazardChange={onHazardChange}
          occurrenceStart={occurrenceStart}
          occurrenceEnd={occurrenceEnd}
          onOccurrenceStartChange={onOccurrenceStartChange}
          onOccurrenceEndChange={onOccurrenceEndChange}
          onRefresh={onRefresh}
        />
      )}
      <div className="active-incidents-scroll">
        {context.length ? (
          <details className="incident-context-evidence">
            <summary>Context and unresolved evidence ({context.length})</summary>
            <p>
              Forecasts, preparedness, historical references and fragments remain source
              evidence. They do not establish a current physical occurrence.
            </p>
            {context.slice(0, contextLimit).map((item) => (
              <article key={item.event_id}>
                <button
                  type="button"
                  aria-label={`Inspect retained ${item.location}`}
                  onClick={() => onSelectIncident(item.event_id)}
                >
                  {disasterLabel(item.disaster)} · {item.location}
                </button>
                <small>
                  {item.discovery_reports?.[0]?.mention_role} · {item.source.publisher}
                </small>
              </article>
            ))}
            {context.length > contextLimit ? (
              <button
                type="button"
                onClick={() => setContextLimit((value) => value + 20)}
              >
                Show more retained evidence
              </button>
            ) : null}
          </details>
        ) : null}
        {snapshot ? (
          <IncidentCoverageStatus
            snapshot={coverageSnapshot ?? snapshot}
            label={compact ? 'Coverage & limitations' : 'View coverage'}
          />
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
                {snapshot.observations?.length} source{' '}
                {snapshot.observations?.length === 1 ? 'observation' : 'observations'}{' '}
                excluded from incident counts
              </summary>
              <p>
                These are source-backed preliminary reports, sensing observations, or
                product records—not separate physical incidents. They remain available
                for provenance review.
              </p>
              <ul>
                {snapshot.observations?.slice(0, 5).map((observation) => (
                  <li key={`${observation.source.source_id}:${observation.event_id}`}>
                    <span>
                      {observationKindLabel(observation)} ·{' '}
                      {formatObservationPeriod(observation)}
                    </span>{' '}
                    · {observation.location} ·{' '}
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
              <h3 id="incident-list-heading">
                {snapshot.publication_scan
                  ? 'Events and candidates'
                  : VIEW_LABELS[view]}
              </h3>
              <span className="incident-result-count">
                Showing {incidents.length}
                {snapshot.total_incident_count !== undefined &&
                snapshot.total_incident_count !== null &&
                snapshot.total_incident_count !== incidents.length
                  ? ` of ${snapshot.total_incident_count}`
                  : ''}{' '}
                {snapshot.total_incident_count === 1 && incidents.length === 1
                  ? 'incident'
                  : 'incidents'}
              </span>
            </div>
            {!snapshot.publication_scan &&
            displayTimeWindow &&
            displayTimeWindow !== '7d' ? (
              <p className="incident-display-filter-note">
                Showing records in the {displayTimeWindow} display window. Provider
                coverage above is unchanged.
              </p>
            ) : null}
            {incidents.length > 0 && !compact ? (
              <AccessibleIncidentIndex
                incidents={incidents}
                retrievedAt={snapshot.retrieved_at}
              />
            ) : null}
            {incidents.length === 0 ? (
              <div className="incident-empty">
                <strong>
                  {snapshot.scan_status === 'running'
                    ? 'Collected events will appear here as the scan runs.'
                    : snapshot.scan_status === 'failed'
                      ? 'Discovery failed. No successful empty result is available.'
                      : query
                        ? isServerSearch
                          ? 'No records match your search.'
                          : 'No loaded records match your search.'
                        : 'No incident records matched this bounded retrieval.'}
                </strong>
                {!snapshot.scan_status || snapshot.scan_status === 'completed' ? (
                  <p>
                    A successful empty result does not prove that no disaster occurred.
                  </p>
                ) : null}
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
                        aria-label={
                          snapshot.publication_scan && !incident.geometry
                            ? `Inspect ${title}`
                            : `Focus ${title} on map`
                        }
                        aria-pressed={selectedIncidentId === incident.event_id}
                        onClick={() => onSelectIncident(incident.event_id)}
                      >
                        <span className="incident-card-heading">
                          <span
                            className="incident-selection-indicator"
                            aria-hidden="true"
                          >
                            {selectedIncidentId === incident.event_id ? (
                              <SelectedIcon />
                            ) : null}
                          </span>
                          <span className="incident-disaster-label">
                            <DisasterIcon disaster={incident.disaster} />
                            {disasterLabel(incident.disaster)}
                          </span>
                          {selectedIncidentId === incident.event_id && (
                            <span className="incident-selected-label">Selected</span>
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
                        <span className="incident-card-meta">
                          <small
                            className={`incident-activity-status incident-activity-status-${incident.activity_status ?? 'unknown'}`}
                          >
                            {activityStatusLabel(incident.activity_status)}
                          </small>
                          <time
                            dateTime={
                              incident.event_time ??
                              incident.source.published_at ??
                              undefined
                            }
                          >
                            {incident.event_time_basis === 'unknown'
                              ? 'Reported: '
                              : ''}
                            {incidentDateOnly(incident) ??
                              (snapshot.availability === 'offline-cache'
                                ? formatTime(
                                    incident.event_time ?? incident.source.published_at,
                                  )
                                : formatRelativeTime(
                                    incident.event_time ?? incident.source.published_at,
                                    snapshot.retrieved_at,
                                  ))}
                          </time>
                        </span>
                      </button>
                      {!compact && (
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
                            <DataAgeBadge
                              kind="source"
                              timestamp={
                                incident.source.updated_at ??
                                incident.source.published_at ??
                                incident.source.retrieved_at
                              }
                              ageSeconds={incident.source.source_age_seconds}
                            />
                            <details className="incident-provenance-graph">
                              <summary>Provenance graph</summary>
                              <ol aria-label={`Provenance for ${incident.event_id}`}>
                                {(incident.evidence_sources?.length
                                  ? incident.evidence_sources
                                  : [incident.source]
                                ).map((source) => (
                                  <li key={`${incident.event_id}:${source.source_id}`}>
                                    <strong>Source observation</strong>{' '}
                                    <a
                                      href={source.canonical_url}
                                      target="_blank"
                                      rel="noreferrer"
                                    >
                                      {source.publisher}
                                    </a>
                                  </li>
                                ))}
                                <li>
                                  <strong>Derived into</strong> normalized evidence
                                </li>
                                <li>
                                  <strong>Supports</strong> physical event{' '}
                                  {incident.physical_event_id ?? incident.event_id}
                                </li>
                              </ol>
                              <small>
                                This trace shows provenance, not proof of causation or
                                completeness.
                              </small>
                            </details>
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
                      )}
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
            {incidents.length > 0 && compact ? (
              <AccessibleIncidentIndex
                incidents={incidents}
                retrievedAt={snapshot.retrieved_at}
              />
            ) : null}
          </section>
        )}
      </div>
    </aside>
  );
}
