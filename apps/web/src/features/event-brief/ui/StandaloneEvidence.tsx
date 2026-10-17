'use client';
import { useEffect, useState } from 'react';
import {
  fetchSectionEvidence,
  type EvidenceSection,
} from '@/features/event-brief/api/sectionEvidenceClient';
import type { StandaloneEvidenceResult } from '@/shared/api/generated/assistant';
import type { CycloneMapLayer } from '@/shared/types/assistant';
import { ExposureInspection } from './ExposureInspection';
import { PhotographCollection } from './PhotographCollection';
import { ReportedAccounts } from './ReportedAccounts';

export function StandaloneEvidence({
  identifier,
  section,
  onForecastLayers,
}: {
  identifier: string;
  section: EvidenceSection;
  onForecastLayers?: (layers: CycloneMapLayer[]) => void;
}) {
  const [state, setState] = useState<{
    key: string;
    evidence?: StandaloneEvidenceResult;
    error?: string;
  }>();
  const key = `${identifier}:${section}`;
  useEffect(() => {
    const controller = new AbortController();
    void fetchSectionEvidence(identifier, section, controller.signal)
      .then((evidence) => {
        if (!controller.signal.aborted) {
          setState({ key, evidence });
          if (section === 'forecast')
            onForecastLayers?.(evidence.forecast_layers ?? []);
        }
      })
      .catch((error) => {
        if (!controller.signal.aborted)
          setState({
            key,
            error:
              error instanceof Error ? error.message : 'Evidence retrieval failed.',
          });
      });
    return () => controller.abort();
  }, [identifier, section, key, onForecastLayers]);
  const current = state?.key === key ? state : undefined;
  if (current?.error) return <p role="status">Error: {current.error}</p>;
  if (!current?.evidence) return <p role="status">Loading {section}…</p>;
  const evidence = current.evidence;
  return (
    <div className="standalone-evidence">
      {section === 'exposure' && (
        <ExposureInspection
          identifier={identifier}
          onResult={(evidence) => setState({ key, evidence })}
        />
      )}
      <p role="status">
        {evidence.state.replaceAll('_', ' ')} · Retrieved{' '}
        {new Date(evidence.retrieved_at).toLocaleString()}
      </p>
      {evidence.state === 'empty' && (
        <p>
          No admitted {section} evidence was returned. This does not establish absence.
        </p>
      )}
      {evidence.state === 'unconfigured' && (
        <p>This section requires operator configuration.</p>
      )}
      {evidence.reported_accounts?.length ? (
        <ReportedAccounts key={key} accounts={evidence.reported_accounts} />
      ) : null}
      {(!evidence.reported_accounts?.length ? (evidence.facts ?? []) : []).map(
        (fact, index) => (
          <p key={index}>
            <strong>
              {fact.label}: {String(fact.value)}
            </strong>{' '}
            · {fact.status} · {fact.source.publisher}
          </p>
        ),
      )}
      {(evidence.narratives ?? []).map((narrative, index) => (
        <p key={index}>{narrative}</p>
      ))}
      {(evidence.warnings ?? []).map(({ alert, association }) => (
        <article key={`${alert.sender}:${alert.identifier}`}>
          <h4>{alert.infos[0]?.event}</h4>
          <p>
            {association.confirmed
              ? 'Explicit incident reference'
              : 'Candidate association'}{' '}
            · {association.rationale}
          </p>
          <p>
            {alert.infos[0]?.headline} · {alert.publisher} · Valid until{' '}
            {alert.infos[0]?.expires ?? 'not reported'}
          </p>
          {alert.canonical_url && (
            <a href={alert.canonical_url} target="_blank" rel="noreferrer">
              Official warning
            </a>
          )}
        </article>
      ))}
      {(evidence.forecast_layers ?? []).map((layer) => (
        <article key={layer.layer_id}>
          <h4>{layer.semantic_role.replaceAll('_', ' ')}</h4>
          <p>
            Storm {layer.storm_id} · issued {layer.issued_at} ·{' '}
            {layer.coordinates.length} source coordinates · {layer.reconciliation}
          </p>
          <p>{layer.limitation}</p>
          <a href={layer.source.canonical_url} target="_blank" rel="noreferrer">
            Source product
          </a>
        </article>
      ))}
      {evidence.exposure && (
        <article>
          <h4>{evidence.exposure.display_label}</h4>
          {evidence.exposure.population_estimates.map((item) => (
            <p key={item.estimate_id}>
              {item.population.toLocaleString()} estimated people ·{' '}
              {item.dataset.publisher} {item.dataset.version} · vintage{' '}
              {item.dataset.vintage} · {item.dataset.resolution_m} m
            </p>
          ))}
          <p>
            {evidence.exposure.assets.length} mapped infrastructure records intersect
            this area.
          </p>
          <p>
            OSM completeness: {evidence.exposure.osm_completeness?.quality ?? 'unknown'}
            . Intersection does not mean affected.
          </p>
        </article>
      )}
      {evidence.humanitarian?.indicators.map((item) => (
        <p key={item.indicator_id}>
          {item.kind.replaceAll('_', ' ')}: {item.value} {item.unit} · {item.source_id}{' '}
          · {item.stale ? 'stale' : 'within freshness policy'}
        </p>
      ))}
      {evidence.humanitarian?.operational_presence.map((item) => (
        <p key={item.presence_id}>
          {item.organization} · {item.sector} · {item.source_id}
        </p>
      ))}
      {evidence.baseline && (
        <p>
          INFORM baseline {evidence.baseline.vintage}: risk{' '}
          {evidence.baseline.risk_index}, vulnerability{' '}
          {evidence.baseline.vulnerability_index}, coping capacity{' '}
          {evidence.baseline.coping_capacity_index}. {evidence.baseline.interpretation}
        </p>
      )}
      {evidence.media ? (
        <PhotographCollection key={key} gallery={evidence.media} />
      ) : null}
      {[...(evidence.limitations ?? []), ...(evidence.humanitarian?.gaps ?? [])].map(
        (limitation, index) => (
          <p className="event-brief-caution" key={index}>
            {limitation}
          </p>
        ),
      )}
    </div>
  );
}
