'use client';

/* eslint-disable @next/next/no-img-element -- USGS artifacts are source-owned evidence and must not be transformed. */

import { useEffect, useState } from 'react';

import {
  fetchEarthquakeContext,
  type EarthquakeContext,
} from '@/features/event-brief/api/earthquakeContextClient';

type EventBriefIncident = {
  event_id: string;
  physical_event_id?: string | null;
  disaster: string;
  country?: {
    name: string;
    association_basis: string;
    distance_km: number | null;
  } | null;
  location: string;
  event_time: string;
  measurements: Array<{
    kind: string;
    value: string | number;
    unit: string | null;
    source_id: string;
  }>;
  provider_ids: string[];
  source_authority: string;
  source: {
    publisher: string;
    canonical_url: string;
    published_at: string | null;
    updated_at: string | null;
    retrieved_at: string;
    snapshot_id: string | null;
  };
};

type EventBriefWarnings = {
  alerts: Array<{
    provider_alert_id: string;
    source_id: string;
    sender?: string;
    event: string;
    affected_area: string;
    publisher: string;
    lifecycle_state?: string;
    effective?: string | null;
    sent?: string | null;
    expires?: string | null;
  }>;
};

const SECTIONS = [
  ['identity', 'Identity'],
  ['observations', 'Observations'],
  ['warnings', 'Warnings'],
  ['forecast', 'Forecast / model'],
  ['exposure', 'Exposure'],
  ['humanitarian', 'Humanitarian'],
  ['imagery', 'Imagery'],
  ['gaps', 'Gaps'],
  ['timeline', 'Timeline'],
  ['provenance', 'Provenance'],
] as const;

type SectionId = (typeof SECTIONS)[number][0];

export function EventBrief({
  incident,
  warnings,
  onGroundView,
  presentation = 'tabs',
}: {
  incident: EventBriefIncident;
  warnings?: EventBriefWarnings;
  onGroundView: () => void;
  presentation?: 'tabs' | 'disclosures';
}) {
  const [section, setSection] = useState<SectionId>('identity');
  const [earthquakeResult, setEarthquakeResult] = useState<{
    eventId: string;
    context?: EarthquakeContext;
  }>();
  const usgsEventId = [incident.event_id, ...incident.provider_ids].find((value) =>
    value.startsWith('usgs:'),
  );
  const earthquakeContext =
    earthquakeResult && earthquakeResult.eventId === usgsEventId
      ? earthquakeResult.context
      : undefined;

  useEffect(() => {
    if (incident.disaster !== 'earthquake' || !usgsEventId) return;
    const controller = new AbortController();
    void fetchEarthquakeContext(usgsEventId, controller.signal)
      .then((context) => setEarthquakeResult({ eventId: usgsEventId, context }))
      .catch(() => setEarthquakeResult({ eventId: usgsEventId }));
    return () => controller.abort();
  }, [incident.disaster, usgsEventId]);

  if (presentation === 'disclosures') {
    return (
      <section
        className="event-brief event-brief-disclosures"
        aria-label="Event evidence"
      >
        {SECTIONS.filter(([id]) => id !== 'timeline').map(([id, label]) => (
          <details key={id} open={id === 'observations' ? true : undefined}>
            <summary>{label}</summary>
            <SectionContent
              section={id}
              incident={incident}
              warnings={warnings}
              earthquakeContext={earthquakeContext}
              onGroundView={onGroundView}
            />
          </details>
        ))}
      </section>
    );
  }

  return (
    <section className="event-brief" aria-label="Event Brief">
      <header className="event-brief-header">
        <div>
          <span>Evidence-native Event Brief</span>
          <h3>{displayIncidentCountry(incident)}</h3>
        </div>
        <span className="event-brief-hazard">
          {incident.disaster.replaceAll('_', ' ')}
        </span>
      </header>
      <div
        className="event-brief-tabs"
        role="tablist"
        aria-label="Event Brief sections"
      >
        {SECTIONS.map(([id, label]) => (
          <button
            key={id}
            type="button"
            role="tab"
            aria-selected={section === id}
            aria-controls="event-brief-panel"
            onClick={() => setSection(id)}
          >
            {label}
          </button>
        ))}
      </div>
      <div id="event-brief-panel" className="event-brief-panel" role="tabpanel">
        <SectionContent
          section={section}
          incident={incident}
          warnings={warnings}
          earthquakeContext={earthquakeContext}
          onGroundView={onGroundView}
        />
      </div>
    </section>
  );
}

function SectionContent({
  section,
  incident,
  warnings,
  onGroundView,
  earthquakeContext,
}: {
  section: SectionId;
  incident: EventBriefIncident;
  warnings?: EventBriefWarnings;
  earthquakeContext?: EarthquakeContext;
  onGroundView: () => void;
}) {
  switch (section) {
    case 'identity':
      return (
        <dl className="event-brief-facts">
          <Fact
            label="Physical event ID"
            value={incident.physical_event_id ?? 'Pending reconciliation'}
          />
          <Fact label="Source event ID" value={incident.event_id} />
          <Fact
            label="Hazard taxonomy"
            value={incident.disaster.replaceAll('_', ' ')}
          />
          <Fact label="Country association" value={countryAssociationLabel(incident)} />
          <Fact label="Source location" value={incident.location} />
        </dl>
      );
    case 'observations':
      return incident.measurements.length ? (
        <ul className="event-brief-list">
          {incident.measurements.map((measurement, index) => (
            <li key={`${measurement.source_id}:${measurement.kind}:${index}`}>
              <strong>{measurement.kind.replaceAll('_', ' ')}</strong>
              <span>
                {measurement.value} {measurement.unit ?? ''}
              </span>
              <small>Source: {measurement.source_id}</small>
            </li>
          ))}
        </ul>
      ) : (
        <Gap>No admitted source observations are available.</Gap>
      );
    case 'warnings':
      return warnings?.alerts.length ? (
        <>
          <p className="event-brief-caution">
            Official warnings remain separate from physical-event observations unless a
            conservative association is recorded.
          </p>
          <ul className="event-brief-list">
            {warnings.alerts.slice(0, 5).map((warning) => (
              <li
                key={`${warning.sender ?? warning.source_id}:${warning.provider_alert_id}`}
              >
                <strong>{warning.event}</strong>
                <span>{warning.affected_area}</span>
                <small>
                  Issuer: {warning.publisher} · {warning.lifecycle_state ?? 'active'} ·
                  valid {warning.effective ?? warning.sent ?? 'not reported'} to{' '}
                  {warning.expires ?? 'not reported'}
                </small>
              </li>
            ))}
          </ul>
        </>
      ) : (
        <Gap>No official warning is conservatively associated with this event.</Gap>
      );
    case 'forecast':
      return incident.disaster === 'earthquake' ? (
        <EarthquakeModelContext context={earthquakeContext} />
      ) : (
        <Gap>No event-associated forecast/model product is currently available.</Gap>
      );
    case 'exposure':
      return (
        <div>
          <h4>Population and assets intersecting a source-backed area</h4>
          <p>
            Exposure analysis uses the exact mapped, forecast, or modelled geometry and
            versioned WorldPop/GHSL and local OSM datasets.
          </p>
          <p className="event-brief-caution">
            People and assets inside that geometry are not verified as affected.
          </p>
        </div>
      );
    case 'humanitarian':
      return (
        <div>
          <p>
            Humanitarian situation reports are listed only when associated source
            evidence exists.
          </p>
          <p className="event-brief-caution">
            INFORM values are baseline vulnerability context, visually separate from
            event impacts.
          </p>
        </div>
      );
    case 'imagery':
      return (
        <div>
          <p>
            Ground view keeps capture dates, coverage masks, sensor readiness, and
            before/after comparison lineage inspectable.
          </p>
          <button type="button" className="event-brief-action" onClick={onGroundView}>
            Open Ground comparison
          </button>
        </div>
      );
    case 'gaps':
      return (
        <ul className="event-brief-list">
          <li>Missing warning geometry is not reconstructed.</li>
          <li>
            Missing imagery or exposure data is reported as unavailable, not zero.
          </li>
          <li>Source coverage does not imply global completeness.</li>
        </ul>
      );
    case 'timeline':
      return (
        <ol className="event-brief-timeline">
          <li>
            <time>{incident.event_time}</time>
            <span>Source-reported event time</span>
          </li>
          {incident.source.published_at ? (
            <li>
              <time>{incident.source.published_at}</time>
              <span>Source publication</span>
            </li>
          ) : null}
          {incident.source.updated_at ? (
            <li>
              <time>{incident.source.updated_at}</time>
              <span>Source update</span>
            </li>
          ) : null}
          <li>
            <time>{incident.source.retrieved_at}</time>
            <span>Monitor retrieval</span>
          </li>
        </ol>
      );
    case 'provenance':
      return (
        <dl className="event-brief-facts">
          <Fact label="Publisher" value={incident.source.publisher} />
          <Fact
            label="Authority role"
            value={incident.source_authority.replaceAll('_', ' ')}
          />
          <Fact
            label="Snapshot"
            value={incident.source.snapshot_id ?? 'Not retained'}
          />
          <Fact label="Provider records" value={incident.provider_ids.join(', ')} />
          <div>
            <dt>Original record</dt>
            <dd>
              <a href={incident.source.canonical_url} target="_blank" rel="noreferrer">
                Open source
              </a>
            </dd>
          </div>
        </dl>
      );
  }
}

function EarthquakeModelContext({ context }: { context?: EarthquakeContext }) {
  const [measure, setMeasure] = useState<'mmi' | 'pga' | 'pgv'>('mmi');
  const layer = context?.shakemap_layers.find((item) => item.measure === measure);
  return (
    <div className="shakemap-legend">
      <h4>USGS earthquake product measures</h4>
      <div className="shakemap-measure-controls" aria-label="ShakeMap measure">
        {(['mmi', 'pga', 'pgv'] as const).map((value) => (
          <button
            key={value}
            type="button"
            aria-pressed={measure === value}
            onClick={() => setMeasure(value)}
          >
            {value.toUpperCase()}
          </button>
        ))}
      </div>
      <p>
        <b>MMI</b> — felt intensity and observed/estimated shaking effects.
      </p>
      <p>
        <b>PGA</b> — peak ground acceleration, shown in %g.
      </p>
      <p>
        <b>PGV</b> — peak ground velocity, shown in cm/s.
      </p>
      {layer ? (
        <div className="shakemap-layer">
          {layer.overlay_url ? (
            <img
              src={layer.overlay_url}
              alt={`USGS ShakeMap ${measure.toUpperCase()} overlay`}
            />
          ) : null}
          {layer.legend_url ? (
            <img
              src={layer.legend_url}
              alt={`USGS ShakeMap ${measure.toUpperCase()} legend`}
            />
          ) : null}
          <p>
            Version {layer.product.version} · updated {layer.product.updated_at} · unit{' '}
            {layer.unit} · maximum {layer.maximum ?? 'not reported'}
          </p>
          <a href={layer.coverage_url} target="_blank" rel="noreferrer">
            Open source coverage grid
          </a>
        </div>
      ) : (
        <p>No event-scoped ShakeMap product is available.</p>
      )}
      {context?.pager ? (
        <p>
          PAGER {context.pager.alert_level || 'unrated'} · version{' '}
          {context.pager.product.version} · {context.pager.exposure_by_intensity.length}{' '}
          intensity exposure bins
        </p>
      ) : null}
      {context?.ground_failure.map((item) => (
        <p key={`${item.product.product_id}:${item.kind}`}>
          {item.kind} · model {item.product.version} · ShakeMap {item.shakemap_version}
        </p>
      ))}
      {context?.aftershock_forecast ? (
        <p>
          Aftershock forecast: {context.aftershock_forecast.model_name} ·{' '}
          {context.aftershock_forecast.advisory_time_frame} · event-region only
        </p>
      ) : null}
      <small>
        Measures retain the supplied product version, grid, units, and meaning and are
        never converted between scales.
      </small>
      <p className="event-brief-caution">
        PAGER, ground-failure, and aftershock values are modelled estimates, not
        verified casualties, losses, or secondary-hazard observations.
      </p>
    </div>
  );
}

function Fact({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt>{label}</dt>
      <dd>{value}</dd>
    </div>
  );
}

function displayIncidentCountry(incident: EventBriefIncident): string {
  return incident.country?.name ?? incident.location;
}

function countryAssociationLabel(incident: EventBriefIncident): string {
  if (!incident.country) return 'Country association unavailable';
  switch (incident.country.association_basis) {
    case 'coordinate_polygon':
      return 'Coordinate within mapped country or territory';
    case 'source_mention':
      return 'Country or territory named by source';
    case 'named_region':
      return 'Verified named-region association';
    case 'nearby_boundary':
      return incident.country.distance_km === null
        ? 'Near a mapped country or territory boundary'
        : `${incident.country.distance_km.toFixed(1)} km from mapped boundary`;
    default:
      return 'Source-preserved country association';
  }
}

function Gap({ children }: { children: string }) {
  return <p className="event-brief-gap">{children}</p>;
}
