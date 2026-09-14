import Image from 'next/image';

import { InvestigationCaseView } from '@/features/assistant/ui/InvestigationCaseView';
import type {
  AssistantReport,
  CommonOperationalPicture,
  DecisionFactStatementType,
  DecisionSupportArtifact,
  DisasterMediaGallery,
  EvidenceClaim,
  EvidenceClaimVariant,
  EvidenceTimelineEntry,
  MultimodalEvidenceState,
} from '@/shared/types/assistant';
import { DataAgeBadge } from '@/shared/ui/DataAgeBadge';

function formatTime(value: string | null | undefined) {
  if (!value) {
    return 'Time unavailable';
  }
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleString();
}

function formatConfidence(value: number | null | undefined) {
  return value === null || value === undefined
    ? 'Confidence not provided'
    : `${Math.round(value * 100)}% model confidence`;
}

function sourceLabel(source: EvidenceClaimVariant['source'] | null | undefined) {
  return source ? `${source.publisher}: ${source.title}` : 'Source unavailable';
}

function ClaimVariantView({
  variant,
  contradiction,
}: {
  variant: EvidenceClaimVariant;
  contradiction: boolean;
}) {
  return (
    <article
      className={`claim-variant${contradiction ? ' claim-variant-contradiction' : ''}`}
    >
      <div className="evidence-badges">
        <span>{contradiction ? 'Contradicting claim' : 'Alternative claim'}</span>
        <span>{variant.status.replaceAll('_', ' ')}</span>
        <span>{variant.disposition}</span>
      </div>
      <p>{variant.value}</p>
      <small>{sourceLabel(variant.source)}</small>
      <DataAgeBadge
        kind="source"
        timestamp={variant.published_at ?? variant.observed_at ?? variant.retrieved_at}
        ageSeconds={variant.source.source_age_seconds}
        state={variant.disposition === 'conflicting' ? 'degraded' : undefined}
      />
      <small>Reconciliation rule: {variant.rule_id}</small>
    </article>
  );
}

function ClaimInspectionView({ claim }: { claim: EvidenceClaim }) {
  const alternatives = claim.alternatives ?? [];
  const contradictions = claim.contradictions ?? [];

  return (
    <article className="claim-inspection" data-testid="evidence-claim">
      <div className="claim-inspection-heading">
        <div>
          <strong>{claim.label}</strong>
          <small>{claim.claim_key}</small>
        </div>
        <div className="evidence-badges">
          <span>{claim.status.replaceAll('_', ' ')}</span>
          {claim.disposition ? <span>{claim.disposition}</span> : null}
        </div>
      </div>
      <p>{claim.value ?? 'No current value was admitted.'}</p>
      <p className="claim-inspection-why">Why: {claim.why}</p>
      {claim.source ? (
        <div className="claim-inspection-source">
          <small>{sourceLabel(claim.source)}</small>
          <DataAgeBadge
            kind="source"
            timestamp={claim.published_at ?? claim.observed_at ?? claim.retrieved_at}
            ageSeconds={claim.source.source_age_seconds}
            state={claim.disposition === 'conflicting' ? 'degraded' : undefined}
          />
        </div>
      ) : null}
      {claim.gap ? <p className="claim-inspection-gap">Gap: {claim.gap}</p> : null}
      {alternatives.length > 0 || contradictions.length > 0 ? (
        <details open={contradictions.length > 0}>
          <summary>
            {contradictions.length > 0
              ? `${contradictions.length} contradiction(s) retained`
              : `${alternatives.length} alternative(s) retained`}
          </summary>
          <div className="claim-variant-list">
            {contradictions.map((variant) => (
              <ClaimVariantView
                key={`${variant.observation_id}:${variant.rule_id}`}
                variant={variant}
                contradiction
              />
            ))}
            {alternatives.map((variant) => (
              <ClaimVariantView
                key={`${variant.observation_id}:${variant.rule_id}`}
                variant={variant}
                contradiction={false}
              />
            ))}
          </div>
        </details>
      ) : null}
    </article>
  );
}

function EvidenceInspectionView({
  claims,
  timeline,
}: {
  claims: EvidenceClaim[];
  timeline: EvidenceTimelineEntry[];
}) {
  if (claims.length === 0 && timeline.length === 0) return null;
  return (
    <>
      {claims.length > 0 ? (
        <section
          className="claim-inspection-section"
          aria-label="Claim-level evidence inspection"
        >
          <div className="evidence-section-heading">
            <h3>Claim-level inspection</h3>
            <span>{claims.length}</span>
          </div>
          <p className="evidence-section-note">
            Current values, source rationale, alternatives, and contradictions remain
            visible as separate evidence.
          </p>
          <div className="claim-inspection-list">
            {claims.map((claim) => (
              <ClaimInspectionView key={claim.claim_id} claim={claim} />
            ))}
          </div>
        </section>
      ) : null}
      {timeline.length > 0 ? (
        <section className="evidence-timeline" aria-label="Report evidence timeline">
          <div className="evidence-section-heading">
            <h3>Evidence timeline</h3>
            <span>{timeline.length}</span>
          </div>
          <div className="evidence-timeline-list">
            {timeline.map((entry) => (
              <article key={entry.entry_id} className="evidence-timeline-entry">
                <div className="evidence-timeline-entry-heading">
                  <strong>{entry.title}</strong>
                  <time dateTime={entry.occurred_at}>
                    {formatTime(entry.occurred_at)}
                  </time>
                </div>
                <div className="evidence-badges">
                  <span>{entry.event_type.replaceAll('_', ' ')}</span>
                  {entry.status ? (
                    <span>{entry.status.replaceAll('_', ' ')}</span>
                  ) : null}
                </div>
                <p>{entry.detail}</p>
                {entry.source ? <small>{sourceLabel(entry.source)}</small> : null}
                <DataAgeBadge
                  kind="source"
                  timestamp={
                    entry.published_at ?? entry.retrieved_at ?? entry.occurred_at
                  }
                  ageSeconds={entry.source?.source_age_seconds}
                />
              </article>
            ))}
          </div>
        </section>
      ) : null}
    </>
  );
}

const DECISION_FACT_LABELS: Record<DecisionFactStatementType, string> = {
  verified_fact: 'Verified source fact',
  preliminary_observation: 'Preliminary source observation',
  source_estimate: 'Source-estimated observation',
  disputed_observation: 'Disputed source observation',
};

function DecisionEvidenceView({ artifact }: { artifact: DecisionSupportArtifact }) {
  return (
    <section className="visual-evidence" aria-label="Decision evidence and estimates">
      <h3>Decision evidence and estimates</h3>
      {artifact.facts.map((fact) => (
        <article className="visual-observation" key={fact.fact_id}>
          <div className="evidence-badges">
            <span>{DECISION_FACT_LABELS[fact.statement_type]}</span>
            <span>Status: {fact.status.replaceAll('_', ' ')}</span>
          </div>
          <p>{fact.statement}</p>
          <small>Sources: {fact.source_ids.join(', ')}</small>
        </article>
      ))}
      {artifact.estimates.map((estimate) => (
        <article className="visual-observation" key={estimate.estimate_id}>
          <div className="evidence-badges">
            <span>DM analytical estimate</span>
            <span>Inferred</span>
          </div>
          <p>{estimate.proposition}</p>
          <strong>
            {Math.round(estimate.probability * 100)}% estimated probability
          </strong>
          {estimate.uncertain_evidence_ids.length > 0 && (
            <small>
              Includes uncertain source evidence:{' '}
              {estimate.uncertain_evidence_ids.join(', ')}
            </small>
          )}
        </article>
      ))}
      <small>
        Scenario: {artifact.scenario_mode.replaceAll('_', ' ')} · Recommendation:{' '}
        {artifact.recommendation_status.replaceAll('_', ' ')} · Advisory only
      </small>
    </section>
  );
}

function VisualEvidenceView({ state }: { state: MultimodalEvidenceState }) {
  const assets = new Map(state.assets.map((asset) => [asset.asset_id, asset]));
  const associations = new Map(
    state.associations.map((association) => [association.asset_id, association]),
  );
  return (
    <section className="visual-evidence" aria-label="Analytical visual evidence">
      <h3>Analytical visual evidence</h3>
      {state.assets.map((asset) => {
        const association = associations.get(asset.asset_id);
        return (
          <div className="visual-asset" key={asset.asset_id}>
            <div className="evidence-badges">
              <span>Operator-supplied image</span>
              <span>{asset.eligibility.replaceAll('_', ' ')}</span>
              <span>Association: {association?.status ?? 'not evaluated'}</span>
            </div>
            <p>{asset.source.attribution}</p>
            <small>
              Captured: {formatTime(asset.captured_at ?? undefined)} · Role:{' '}
              {asset.capture_role.replaceAll('_', ' ')}
            </small>
          </div>
        );
      })}
      {state.observations.map((observation) => {
        const asset = assets.get(observation.asset_id);
        const result =
          observation.kind === 'damage_assessment'
            ? `Visible damage: ${observation.damage_level?.replaceAll('_', ' ') ?? 'unknown'}`
            : (observation.answer ?? 'The visual model abstained.');
        return (
          <article className="visual-observation" key={observation.observation_id}>
            <div className="evidence-badges">
              <span>Analytical · AI-generated</span>
              <span>Status: {observation.status}</span>
              <span>Modality: image</span>
            </div>
            {observation.question && <p>Question: {observation.question}</p>}
            <strong>{result}</strong>
            <p>{observation.uncertainty}</p>
            <small>
              {formatConfidence(observation.confidence)} · Attribution:{' '}
              {asset?.source.attribution ?? 'Unavailable'}
            </small>
            <details>
              <summary>Analysis configuration and cues</summary>
              <p>
                Model: {observation.configuration.model_id} · Analysis:{' '}
                {observation.configuration.analysis_version} · Prompt:{' '}
                {observation.configuration.prompt_version} · Output cap:{' '}
                {observation.configuration.maximum_output_tokens} tokens · Temperature:{' '}
                {observation.configuration.temperature} · Seed:{' '}
                {observation.configuration.seed}
              </p>
              {observation.visual_cues.length > 0 && (
                <p>Visible cues: {observation.visual_cues.join('; ')}</p>
              )}
              {observation.safety_rule_ids.length > 0 && (
                <p>Safety rules: {observation.safety_rule_ids.join(', ')}</p>
              )}
            </details>
          </article>
        );
      })}
    </section>
  );
}

function CopSummary({ cop }: { cop: CommonOperationalPicture }) {
  return (
    <section className="cop-summary" aria-label="Common operational picture details">
      <h3>Common operational picture</h3>
      <p>
        Status: <strong>{cop.status}</strong>
      </p>
      {cop.layers.map((layer) => (
        <div key={layer.layer_id} className="cop-layer-summary">
          <strong>{layer.title}</strong>
          <span className="authority-label">
            {layer.layer_type === 'source'
              ? 'Source/official geometry'
              : 'Analytical · AI-generated geometry'}
          </span>
          <small>
            Layer status: {layer.status} · Uncertainty: {layer.uncertainty}
          </small>
          <small>Layer attribution: {layer.attribution}</small>
          {layer.features.map((feature) => (
            <div key={feature.feature_id} className="cop-feature-summary">
              <span>
                {feature.semantic_kind.replaceAll('_', ' ')} · Status: {feature.status}
              </span>
              <small>Uncertainty: {feature.uncertainty}</small>
              <small>Attribution: {feature.attribution}</small>
            </div>
          ))}
        </div>
      ))}
    </section>
  );
}

function SourceMediaGallery({ gallery }: { gallery: DisasterMediaGallery }) {
  return (
    <section
      className="source-media-gallery"
      aria-label="Event-associated source photos"
    >
      <div className="source-media-heading">
        <h3>Event-associated source photos</h3>
        <small>
          {gallery.items.length} shown · {gallery.rejected_count} rejected
        </small>
      </div>
      {gallery.warnings.map((warning, index) => (
        <p className="source-media-warning" key={`media-warning-${index}`}>
          {warning}
        </p>
      ))}
      <div className="source-media-grid">
        {gallery.items.map((item) => (
          <figure className="source-media-card" key={item.media_id}>
            <Image
              src={item.image_url}
              alt={item.caption}
              loading="lazy"
              width={item.width}
              height={item.height}
              unoptimized
            />
            <figcaption>
              <div className="evidence-badges">
                <span>{item.role.replaceAll('_', ' ')}</span>
                <span>{item.association_status.replaceAll('_', ' ')}</span>
                <span>
                  {item.rights_status === 'source_preview'
                    ? 'Source-controlled preview'
                    : 'Licensed reuse'}
                </span>
              </div>
              <strong>{item.caption}</strong>
              <span>
                Credit: {item.credit} ({item.credit_kind})
              </span>
              <small>
                {item.captured_at
                  ? `Captured: ${formatTime(item.captured_at)}`
                  : `Published: ${formatTime(item.published_at)}`}
              </small>
              <a href={item.source_page_url} target="_blank" rel="noreferrer">
                Source: {item.publisher}
              </a>
              <details>
                <summary>Association and uncertainty</summary>
                <p>{item.association_detail}</p>
                <p>{item.uncertainty}</p>
                <small>{item.association_rule_ids.join(', ')}</small>
              </details>
            </figcaption>
          </figure>
        ))}
      </div>
    </section>
  );
}

export function DisasterReportView({
  report,
  message,
}: {
  report: AssistantReport;
  message: string;
}) {
  if (report.investigationCase) {
    return <InvestigationCaseView investigationCase={report.investigationCase} />;
  }
  const warnings =
    report.warnings.length > 0
      ? report.warnings
      : [
          'This report is partial because reliable event-specific evidence was not available.',
        ];
  return (
    <div className="disaster-report">
      {report.partial && (
        <details className="report-warning" role="status">
          <summary>
            {warnings.length} coverage {warnings.length === 1 ? 'note' : 'notes'}
          </summary>
          <div className="report-warning-content">
            {warnings.map((warning, index) => (
              <p key={`report-warning-${index}`}>{warning}</p>
            ))}
          </div>
        </details>
      )}
      {report.selectedEvent && (
        <div className="report-event">
          <strong>{report.selectedEvent.location}</strong>
          <span>
            {formatTime(report.selectedEvent.event_time)}
            {report.selectedEvent.measurements.length > 0
              ? ` · ${report.selectedEvent.measurements
                  .map(
                    (measurement) =>
                      `${measurement.kind} ${measurement.value}${
                        measurement.unit ? ` ${measurement.unit}` : ''
                      } · Source: ${measurement.source_id}`,
                  )
                  .join(', ')}`
              : ''}
          </span>
          <DataAgeBadge
            kind="source"
            timestamp={
              report.selectedEvent.source.updated_at ??
              report.selectedEvent.source.published_at ??
              report.selectedEvent.source.retrieved_at
            }
            ageSeconds={report.selectedEvent.source.source_age_seconds}
          />
          {report.selectedEvent.geography_status === 'country_associated_offshore' && (
            <small>Country-associated offshore event</small>
          )}
        </div>
      )}
      <div className="report-sections">
        {report.sections.map((section, index) => (
          <section key={`report-section-${index}`}>
            <h3>{section.title}</h3>
            <p>{section.content}</p>
          </section>
        ))}
      </div>
      <EvidenceInspectionView claims={report.claims} timeline={report.timeline} />
      {report.mediaGallery && <SourceMediaGallery gallery={report.mediaGallery} />}
      {report.decisionSupport && (
        <DecisionEvidenceView artifact={report.decisionSupport} />
      )}
      {report.multimodal && <VisualEvidenceView state={report.multimodal} />}
      {report.commonOperationalPicture && (
        <CopSummary cop={report.commonOperationalPicture} />
      )}
      {report.sources.length > 0 && (
        <div className="report-sources">
          <h3>Source timestamps</h3>
          {report.sources.map((source, index) => (
            <a
              key={`report-source-${index}`}
              href={source.canonical_url}
              target="_blank"
              rel="noreferrer"
            >
              <span>
                {source.publisher}: {source.title}
              </span>
              <small>
                Published/updated:{' '}
                {formatTime(source.updated_at ?? source.published_at)}
                {' · '}Retrieved: {formatTime(source.retrieved_at)}
              </small>
              <DataAgeBadge
                kind="source"
                timestamp={
                  source.updated_at ?? source.published_at ?? source.retrieved_at
                }
                ageSeconds={source.source_age_seconds}
              />
              {source.snapshot_id && <small>Snapshot: {source.snapshot_id}</small>}
            </a>
          ))}
        </div>
      )}
      {report.investigation && (
        <details className="investigation-summary">
          <summary>Investigation details</summary>
          <p>
            Status: <strong>{report.investigation.status}</strong>
            {report.investigation.geographic_scope &&
              ` / scope ${report.investigation.geographic_scope}`}
          </p>
          {report.investigation.triage_priority && (
            <p>
              Internal triage: <strong>{report.investigation.triage_priority}</strong>
              {report.investigation.triage_action &&
                ` / ${report.investigation.triage_action}`}
              {report.investigation.triage_autonomy_mode &&
                ` / ${report.investigation.triage_autonomy_mode}`}
              {report.investigation.triage_requires_human_intervention
                ? ' / Human intervention required'
                : ''}
            </p>
          )}
          {report.investigation.decision_autonomy_mode && (
            <p>
              Bounded decision:{' '}
              <strong>{report.investigation.decision_action ?? 'none'}</strong>
              {` / ${report.investigation.decision_autonomy_mode}`}
              {report.investigation.decision_state_revision != null &&
                ` / state r${report.investigation.decision_state_revision}`}
              {report.investigation.decision_active_internal_states?.length
                ? ` / ${report.investigation.decision_active_internal_states.join(', ')}`
                : ''}
              {report.investigation.decision_requires_human_intervention
                ? ' / Human intervention required'
                : ''}
            </p>
          )}
          {(report.investigation.specialist_handoff_count ?? 0) > 0 && (
            <p>
              Specialist handoffs:{' '}
              <strong>{report.investigation.specialist_handoff_count}</strong>
              {report.investigation.specialist_roles?.length
                ? ` / ${report.investigation.specialist_roles.join(', ')}`
                : ''}
            </p>
          )}
          {report.investigation.collaboration_status && (
            <p>
              Collaboration:{' '}
              <strong>{report.investigation.collaboration_status}</strong>
              {` / ${report.investigation.collaboration_finding_count ?? 0} findings`}
              {report.investigation.collaboration_iterations != null &&
                ` / ${report.investigation.collaboration_iterations} iteration(s)`}
              {(report.investigation.collaboration_deadlock_count ?? 0) > 0 &&
                ` / ${report.investigation.collaboration_deadlock_count} deadlock(s)`}
              {report.investigation.collaboration_fallback_reason
                ? ` / ${report.investigation.collaboration_fallback_reason}`
                : ''}
            </p>
          )}
          {report.investigation.coordination_supervisor_status && (
            <p>
              Coordination supervisor:{' '}
              <strong>{report.investigation.coordination_supervisor_status}</strong>
              {report.investigation.coordination_sufficient
                ? ' / sufficient'
                : ' / default plan retained'}
              {report.investigation.coordination_termination_reason &&
                ` / ${report.investigation.coordination_termination_reason}`}
              {report.investigation.coordination_missing_finding_keys?.length
                ? ` / missing ${report.investigation.coordination_missing_finding_keys.join(', ')}`
                : ''}
              {report.investigation.coordination_analytical_focus
                ? ` / focus ${report.investigation.coordination_analytical_focus}`
                : ''}
              {report.investigation.coordination_analytical_parameter_set_id
                ? ` / ${report.investigation.coordination_analytical_parameter_set_id}`
                : ''}
              {report.investigation.coordination_analytical_release_id
                ? ` / release ${report.investigation.coordination_analytical_release_id}`
                : ''}
            </p>
          )}
          {report.investigation.coordination_final_rationale && (
            <p>{report.investigation.coordination_final_rationale}</p>
          )}
          {report.investigation.actions.length > 0 && (
            <>
              <h3>Completed actions</h3>
              <ul>
                {report.investigation.actions.map((action, index) => (
                  <li key={`action-${index}`}>{action}</li>
                ))}
              </ul>
            </>
          )}
          {report.investigation.capability_gaps.length > 0 && (
            <>
              <h3>Capability gaps</h3>
              <ul>
                {report.investigation.capability_gaps.map((gap, index) => (
                  <li key={`capability-gap-${index}`}>{gap}</li>
                ))}
              </ul>
            </>
          )}
          {report.investigation.source_ids.length > 0 && (
            <p>Sources considered: {report.investigation.source_ids.join(', ')}</p>
          )}
        </details>
      )}
      <details className="report-text">
        <summary>Text report</summary>
        <p>{message}</p>
      </details>
    </div>
  );
}
