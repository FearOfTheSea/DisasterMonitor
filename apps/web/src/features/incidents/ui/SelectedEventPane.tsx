'use client';

import { useEffect, useRef, useState } from 'react';

import { EventBrief } from '@/features/event-brief/public';
import {
  displayActiveIncidentContext,
  displayActiveIncidentCountry,
  type IncidentMapRecord,
} from '@/features/incidents/model/activeIncidents';
import { DisasterIcon } from './DisasterIcon';
import { disasterLabel, relatedInvestigation } from './incidentPresentation';
import type { CycloneMapLayer } from '@/shared/types/assistant';
import type { WeatherAlertsSnapshot } from '@/features/weather/public';

type Tab = 'overview' | 'evidence' | 'timeline';
const TABS: readonly Tab[] = ['overview', 'evidence', 'timeline'];

function dateTime(value: string | null): string {
  if (!value) return 'Unknown';
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
  const [tab, setTab] = useState<Tab>('overview');
  const heading = useRef<HTMLHeadingElement>(null);
  const tabList = useRef<HTMLDivElement>(null);
  useEffect(() => {
    heading.current?.focus();
  }, [incident.event_id]);
  const context = displayActiveIncidentContext(incident);
  const hazardLabel = disasterLabel(incident.disaster).toLowerCase();
  const hazardArticle = /^[aeiou]/.test(hazardLabel) ? 'an' : 'a';
  const sources = incident.evidence_sources?.length
    ? incident.evidence_sources
    : [incident.source];
  const timeline = [
    {
      label: 'Source-reported event time',
      time: incident.event_time_basis === 'unknown' ? undefined : incident.event_time,
    },
    { label: 'News first published', time: incident.detection?.news_break_at },
    {
      label: 'First observed by monitoring',
      time: incident.detection?.first_observed_at,
    },
    { label: 'Source publication', time: incident.source.published_at },
    { label: 'Source update', time: incident.source.updated_at },
    { label: 'Visible in monitoring', time: incident.detection?.monitor_visible_at },
    { label: 'Monitor retrieval', time: incident.source.retrieved_at },
  ].filter((entry): entry is { label: string; time: string } => Boolean(entry.time));

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
            : 'Event: '}
          <time
            dateTime={incident.event_time ?? incident.source.published_at ?? undefined}
          >
            {dateTime(incident.event_time ?? incident.source.published_at)}
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
            <section>
              <h3>What is known</h3>
              <p>
                {incident.source.publisher} reports {hazardArticle} {hazardLabel} at{' '}
                {incident.location}.{' '}
                {incident.event_time_basis === 'unknown'
                  ? 'The event time is unresolved; the timestamp above is publication time.'
                  : 'The source records the event time above.'}
              </p>
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
              {incident.verification_status === 'provisional_news_detected' ? (
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
            {incident.discovery_reports?.length ? (
              <section aria-label="Discovery reporting">
                <h3>Attributed discovery reports</h3>
                <p>
                  Reporting is evidence of a claim, not automatic confirmation. Shared
                  origins are not independent confirmation; unknown lineage remains
                  uncertain.
                </p>
                <ul className="event-source-list">
                  {incident.discovery_reports.map((report) => (
                    <li key={report.source.canonical_url}>
                      <a
                        href={report.source.canonical_url}
                        target="_blank"
                        rel="noreferrer"
                      >
                        {report.source.publisher}: {report.source.title}
                      </a>
                      <p>
                        Published:{' '}
                        {report.source.published_at
                          ? dateTime(report.source.published_at)
                          : 'Unknown'}{' '}
                        · Updated:{' '}
                        {report.source.updated_at
                          ? dateTime(report.source.updated_at)
                          : 'Unknown'}{' '}
                        · Indexed:{' '}
                        {report.indexed_at ? dateTime(report.indexed_at) : 'Unknown'} ·
                        Retrieved: {dateTime(report.source.retrieved_at)}
                      </p>
                      {report.origin ? (
                        <p>Shared reporting origin: {report.origin}</p>
                      ) : (
                        <p>Reporting independence unknown.</p>
                      )}
                      {report.fatality_evidence?.length ? (
                        report.fatality_evidence.map((claim) => (
                          <blockquote key={claim}>
                            {claim}
                            <br />
                            Reported by {report.source.publisher}; unverified claim.
                          </blockquote>
                        ))
                      ) : (
                        <p>
                          No affirmative fatality evidence extracted. Unknown does not
                          mean zero.
                        </p>
                      )}
                    </li>
                  ))}
                </ul>
                {!incident.geometry ? (
                  <p>
                    Location unresolved. This event remains inspectable in the list.
                  </p>
                ) : null}
              </section>
            ) : null}
            <div className="event-actions">
              <button type="button" onClick={onAsk}>
                {relatedInvestigation(incident).label}
              </button>
              <button type="button" onClick={onGroundView}>
                Open Ground view
              </button>
            </div>
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
                  <time dateTime={entry.time}>{dateTime(entry.time)}</time>
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
