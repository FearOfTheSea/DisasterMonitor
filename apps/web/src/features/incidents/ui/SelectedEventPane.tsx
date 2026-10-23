'use client';

import { useEffect, useRef, useState } from 'react';

import { formatCalendarPeriod } from '@/shared/model/calendarPeriod';

import { EventBrief } from '@/features/event-brief/public';
import {
  displayActiveIncidentContext,
  displayActiveIncidentCountry,
  isContextOnlyIncident,
  type IncidentMapRecord,
} from '@/features/incidents/model/activeIncidents';
import { ArticleCollection } from './ArticleCollection';
import { StandaloneEvidence } from '@/features/event-brief/public';
import { DisasterIcon } from './DisasterIcon';
import { disasterLabel, relatedInvestigation } from './incidentPresentation';
import type { CycloneMapLayer } from '@/shared/types/assistant';
import type { WeatherAlertsSnapshot } from '@/features/weather/public';

type Tab = 'overview' | 'evidence' | 'timeline';
const TABS: readonly Tab[] = ['overview', 'evidence', 'timeline'];

function dateTime(
  value: string | null,
  precision?: string,
  end?: string | null,
): string {
  if (!value) return 'Unknown';
  if (precision === 'range') return formatCalendarPeriod(value, end);
  if (precision === 'day')
    return `${value.slice(0, 10)} (date only; exact time unknown)`;
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
}

function groupedMeasurements(measurements: IncidentMapRecord['measurements']) {
  const groups = new Map<
    string,
    {
      measurement: IncidentMapRecord['measurements'][number];
      sourceIds: string[];
    }
  >();
  for (const measurement of measurements) {
    const key = JSON.stringify([measurement.kind, measurement.value, measurement.unit]);
    const group = groups.get(key);
    if (group) {
      if (!group.sourceIds.includes(measurement.source_id)) {
        group.sourceIds.push(measurement.source_id);
      }
    } else {
      groups.set(key, { measurement, sourceIds: [measurement.source_id] });
    }
  }
  return [...groups.values()];
}

export function SelectedEventPane({
  incident,
  snapshotRetrievedAt,
  warnings,
  onClose,
  onAsk,
  onGroundView,
  onForecastLayers,
}: {
  incident: IncidentMapRecord;
  snapshotRetrievedAt: string;
  warnings?: WeatherAlertsSnapshot;
  onClose: () => void;
  onAsk: () => void;
  onGroundView: () => void;
  onForecastLayers?: (layers: CycloneMapLayer[]) => void;
}) {
  const [photosOpen, setPhotosOpen] = useState(false);
  const [tab, setTab] = useState<Tab>('overview');
  const heading = useRef<HTMLHeadingElement>(null);
  const tabList = useRef<HTMLDivElement>(null);
  useEffect(() => {
    heading.current?.focus();
  }, [incident.event_id]);
  const context = displayActiveIncidentContext(incident);
  const contextOnly = isContextOnlyIncident(incident);
  const locationIsHeadline =
    Boolean(incident.discovery_reports?.length) &&
    incident.location === incident.source.title &&
    !incident.discovery_reports?.some((report) => report.location?.trim());
  const hazardLabel = disasterLabel(incident.disaster).toLowerCase();
  const hazardArticle = /^[aeiou]/.test(hazardLabel) ? 'an' : 'a';
  const sources = incident.evidence_sources?.length
    ? incident.evidence_sources
    : [incident.source];
  const timeline: Array<{
    label: string;
    time: string | null | undefined;
    precision?: string;
    end?: string | null;
  }> = [
    {
      label: 'Source-reported event time',
      time: incident.event_time_basis === 'unknown' ? undefined : incident.event_time,
      precision: incident.event_time_precision,
      end: incident.event_time_end,
    },
    { label: 'News first published', time: incident.detection?.news_break_at },
    {
      label: 'First observed by monitoring',
      time: incident.detection?.first_observed_at,
    },
    {
      label: 'Source publication',
      time: incident.source.published_at,
      precision: incident.source.publication_precision,
    },
    { label: 'Source update', time: incident.source.updated_at },
    { label: 'Visible in monitoring', time: incident.detection?.monitor_visible_at },
    { label: 'Monitor retrieval', time: incident.source.retrieved_at },
  ].filter((entry) => Boolean(entry.time));

  return (
    <aside className="selected-event-pane" aria-labelledby="selected-event-heading">
      <header className="selected-event-header">
        <button type="button" className="event-back" onClick={onClose}>
          ← Back to events
        </button>
        <p className="event-location-label">{displayActiveIncidentCountry(incident)}</p>
        <h2 id="selected-event-heading" ref={heading} tabIndex={-1}>
          <DisasterIcon disaster={incident.disaster} />{' '}
          {disasterLabel(incident.disaster)}
        </h2>
        {context ? <p className="event-source-location">{context}</p> : null}
        <p className="event-time-line">
          {incident.event_time_basis === 'unknown'
            ? 'Event time unresolved. Article published: '
            : incident.event_time_precision === 'range'
              ? 'Reported event period: '
              : 'Event: '}
          <time
            dateTime={incident.event_time ?? incident.source.published_at ?? undefined}
          >
            {dateTime(
              incident.event_time ?? incident.source.published_at,
              incident.event_time
                ? incident.event_time_precision
                : incident.source.publication_precision,
              incident.event_time_end,
            )}
          </time>
        </p>
        <p className="event-time-line">
          Snapshot retrieved:{' '}
          <time dateTime={snapshotRetrievedAt}>{dateTime(snapshotRetrievedAt)}</time>
        </p>
      </header>
      <div
        className="selected-event-tabs"
        role="tablist"
        aria-label="Event details"
        ref={tabList}
        onKeyDown={(event) => {
          const index = TABS.indexOf(tab);
          const nextIndex =
            event.key === 'ArrowRight'
              ? (index + 1) % TABS.length
              : event.key === 'ArrowLeft'
                ? (index - 1 + TABS.length) % TABS.length
                : event.key === 'Home'
                  ? 0
                  : event.key === 'End'
                    ? TABS.length - 1
                    : null;
          if (nextIndex === null) return;
          event.preventDefault();
          setTab(TABS[nextIndex]);
          tabList.current
            ?.querySelectorAll<HTMLButtonElement>('[role="tab"]')
            [nextIndex]?.focus();
        }}
      >
        {TABS.map((value) => (
          <button
            key={value}
            id={`selected-event-tab-${value}`}
            type="button"
            role="tab"
            aria-selected={tab === value}
            aria-controls="selected-event-tab-panel"
            tabIndex={tab === value ? 0 : -1}
            onClick={() => setTab(value)}
          >
            {value[0].toUpperCase() + value.slice(1)}
          </button>
        ))}
      </div>
      <div
        id="selected-event-tab-panel"
        className="selected-event-body"
        role="tabpanel"
        aria-labelledby={`selected-event-tab-${tab}`}
        tabIndex={0}
      >
        {tab === 'overview' && (
          <>
            <div className="event-actions">
              <button type="button" onClick={onAsk}>
                {relatedInvestigation(incident).label}
              </button>
              <button type="button" onClick={onGroundView}>
                Find imagery
              </button>
            </div>
            <section>
              <h3>What is known</h3>
              {contextOnly || incident.identity_status ? (
                <p className="event-uncertainty">
                  {contextOnly
                    ? 'Retained source context'
                    : incident.identity_status === 'candidate'
                      ? 'Unresolved event candidate'
                      : 'Associated physical event'}{' '}
                  · Source reporting remains unverified.
                </p>
              ) : null}
              {incident.association_reasons?.length ? (
                <details>
                  <summary>Why reports are associated</summary>
                  <ul>
                    {incident.association_reasons.map((reason) => (
                      <li key={reason}>{reason}</li>
                    ))}
                  </ul>
                </details>
              ) : null}
              {contextOnly ? (
                <p>
                  This source passage is retained as context. It does not establish a
                  current {hazardLabel} occurrence
                  {locationIsHeadline ? null : ` at ${incident.location}`}.
                  {locationIsHeadline ? ' The reported place is unresolved.' : null}
                </p>
              ) : (
                <p>
                  {incident.source.publisher} reports {hazardArticle} {hazardLabel}
                  {locationIsHeadline ? null : ` at ${incident.location}`}.{' '}
                  {locationIsHeadline ? 'The reported place is unresolved. ' : null}
                  {incident.event_time_basis === 'unknown'
                    ? 'The event time is unresolved; the timestamp above is publication time.'
                    : 'The source records the event time above.'}
                </p>
              )}
              {incident.measurements.length > 0 ? (
                <dl className="event-measurements">
                  {groupedMeasurements(incident.measurements).map(
                    ({ measurement, sourceIds }) => (
                      <div
                        key={JSON.stringify([
                          measurement.kind,
                          measurement.value,
                          measurement.unit,
                        ])}
                      >
                        <dt>{measurement.kind.replaceAll('_', ' ')}</dt>
                        <dd>
                          {measurement.value} {measurement.unit ?? ''}
                          <small>
                            {sourceIds.length}{' '}
                            {sourceIds.length === 1 ? 'source' : 'sources'}:{' '}
                            {sourceIds.join(', ')}
                          </small>
                        </dd>
                      </div>
                    ),
                  )}
                </dl>
              ) : (
                <p>No source-backed measurements are available for this record.</p>
              )}
              {incident.geometry?.estimated ? (
                <p className="event-uncertainty">
                  Mapped position is estimated from the source record.
                </p>
              ) : null}
              {incident.discovery_reports?.length && incident.geometry ? (
                <section aria-label="Mapped context">
                  <p>{incident.geometry.description}</p>
                  {sources
                    .filter(
                      (source) => source.source_id === incident.geometry?.source_id,
                    )
                    .map((source) => (
                      <a
                        key={source.canonical_url}
                        href={source.canonical_url}
                        target="_blank"
                        rel="noreferrer"
                      >
                        Map source: {source.publisher}
                      </a>
                    ))}
                </section>
              ) : null}
              {!contextOnly &&
              incident.verification_status === 'provisional_news_detected' ? (
                <p className="event-uncertainty">
                  Preliminary news report. Authoritative confirmation is pending.
                </p>
              ) : null}
            </section>
            <section>
              <h3>What remains unclear</h3>
              <p>
                This source record alone does not establish verified impacts. Evidence
                and coverage limits are detailed in the Evidence tab.
              </p>
            </section>
            {!incident.discovery_reports?.length ? (
              <section>
                <h3>Sources</h3>
                <ul className="event-source-list">
                  {sources.map((source) => (
                    <li key={`${source.source_id}:${source.canonical_url}`}>
                      <a href={source.canonical_url} target="_blank" rel="noreferrer">
                        {source.publisher}: {source.title}
                      </a>
                    </li>
                  ))}
                </ul>
              </section>
            ) : null}
            {incident.discovery_reports?.length ? (
              <>
                <ArticleCollection
                  key={incident.event_id}
                  reports={incident.discovery_reports}
                  notices={incident.collection_notices}
                  mappedGeometry={incident.geometry}
                />
                <details onToggle={(event) => setPhotosOpen(event.currentTarget.open)}>
                  <summary>Article photographs</summary>
                  {photosOpen ? (
                    <StandaloneEvidence
                      identifier={incident.event_id}
                      section="media"
                    />
                  ) : null}
                </details>
              </>
            ) : null}
          </>
        )}
        {tab === 'evidence' && incident.event_time_basis === 'unknown' ? (
          <p>
            Event time is unresolved. Inspect the attributed discovery reports in
            Overview. Publication time cannot target event evidence or imagery.
          </p>
        ) : (
          tab === 'evidence' && (
            <EventBrief
              incident={incident}
              warnings={warnings}
              onGroundView={onGroundView}
              onForecastLayers={onForecastLayers}
              presentation="disclosures"
            />
          )
        )}
        {tab === 'timeline' &&
          (timeline.length ? (
            <ol className="event-timeline">
              {timeline.map((entry) => (
                <li key={entry.label}>
                  <time dateTime={entry.time ?? undefined}>
                    {dateTime(entry.time ?? null, entry.precision, entry.end)}
                  </time>
                  <span>{entry.label}</span>
                </li>
              ))}
            </ol>
          ) : (
            <p>No source timestamps are available for this event.</p>
          ))}
      </div>
    </aside>
  );
}
