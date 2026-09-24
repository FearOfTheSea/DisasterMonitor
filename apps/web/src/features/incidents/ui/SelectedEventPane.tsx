'use client';

import { useEffect, useRef, useState } from 'react';

import { EventBrief } from '@/features/event-brief/public';
import {
  displayActiveIncidentContext,
  displayActiveIncidentCountry,
  type IncidentMapRecord,
} from '@/features/incidents/model/activeIncidents';
import { DisasterIcon } from './DisasterIcon';
import { disasterLabel } from './incidentPresentation';
import type { WeatherAlertsSnapshot } from '@/features/weather/public';

type Tab = 'overview' | 'evidence' | 'timeline';
const TABS: readonly Tab[] = ['overview', 'evidence', 'timeline'];

function dateTime(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
}

export function SelectedEventPane({
  incident,
  snapshotRetrievedAt,
  warnings,
  onClose,
  onAsk,
  onGroundView,
}: {
  incident: IncidentMapRecord;
  snapshotRetrievedAt: string;
  warnings?: WeatherAlertsSnapshot;
  onClose: () => void;
  onAsk: () => void;
  onGroundView: () => void;
}) {
  const [tab, setTab] = useState<Tab>('overview');
  const heading = useRef<HTMLHeadingElement>(null);
  const tabList = useRef<HTMLDivElement>(null);
  useEffect(() => {
    heading.current?.focus();
  }, [incident.event_id]);
  const context = displayActiveIncidentContext(incident);
  const sources = incident.evidence_sources?.length
    ? incident.evidence_sources
    : [incident.source];
  const timeline = [
    { label: 'Source-reported event time', time: incident.event_time },
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
          Event:{' '}
          <time dateTime={incident.event_time}>{dateTime(incident.event_time)}</time>
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
                {incident.source.publisher} reports a{' '}
                {disasterLabel(incident.disaster).toLowerCase()} at {incident.location}.
                The source records the event time above.
              </p>
              {incident.measurements.length > 0 ? (
                <dl className="event-measurements">
                  {incident.measurements.map((measurement, index) => (
                    <div key={`${measurement.source_id}:${measurement.kind}:${index}`}>
                      <dt>{measurement.kind.replaceAll('_', ' ')}</dt>
                      <dd>
                        {measurement.value} {measurement.unit ?? ''}
                      </dd>
                    </div>
                  ))}
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
                  <li key={source.source_id}>
                    <a href={source.canonical_url} target="_blank" rel="noreferrer">
                      {source.publisher}: {source.title}
                    </a>
                  </li>
                ))}
              </ul>
            </section>
            <div className="event-actions">
              <button type="button" onClick={onAsk}>
                Ask about this event
              </button>
              <button type="button" onClick={onGroundView}>
                Open Ground view
              </button>
            </div>
          </>
        )}
        {tab === 'evidence' && (
          <EventBrief
            incident={incident}
            warnings={warnings}
            onGroundView={onGroundView}
            presentation="disclosures"
          />
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
