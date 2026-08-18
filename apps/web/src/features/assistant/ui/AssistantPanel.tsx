'use client';

import { FormEvent, useState } from 'react';
import Image from 'next/image';

import type {
  AssistantReport,
  CommonOperationalPicture,
  ConversationMessage,
  ConversationStatus,
  DecisionFactStatementType,
  DecisionSupportArtifact,
  MultimodalEvidenceState,
  DisasterMediaGallery,
} from '@/shared/types/assistant';

type AssistantPanelProps = {
  messages: ConversationMessage[];
  status: ConversationStatus;
  error: string | null;
  onSubmit: (question: string) => Promise<void>;
  onClear: () => void;
};

function formatTime(value: string | undefined) {
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

function DisasterReportView({
  report,
  message,
}: {
  report: AssistantReport;
  message: string;
}) {
  return (
    <div className="disaster-report">
      {report.partial && (
        <div className="report-warning" role="status">
          {(report.warnings.length > 0
            ? report.warnings
            : [
                'This report is partial because reliable event-specific evidence was not available.',
              ]
          ).map((warning, index) => (
            <p key={`report-warning-${index}`}>{warning}</p>
          ))}
        </div>
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

export function AssistantPanel({
  messages,
  status,
  error,
  onSubmit,
  onClear,
}: AssistantPanelProps) {
  const [question, setQuestion] = useState('');
  const isLoading = status === 'loading';

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!question.trim() || isLoading) {
      return;
    }
    const submittedQuestion = question;
    setQuestion('');
    await onSubmit(submittedQuestion);
  }

  return (
    <aside className="assistant-panel" aria-label="Disaster Monitor assistant">
      <header className="assistant-panel-header">
        <h2>Map assistant</h2>
        <p>Agent-first routing with local Qwen and trusted source tools.</p>
      </header>
      <div className="availability-note">
        Source-backed current disaster reports are available for recognized requests;
        unsupported coverage is reported explicitly. Selected events can include bounded
        source-photo previews when date, hazard, geography, credit, and source policy
        agree. Operator-supplied imagery remains a separate analytical path.
      </div>
      <div className="message-list" aria-live="polite">
        {messages.length === 0 ? (
          <p className="empty-state">Your conversation will appear here.</p>
        ) : (
          messages.map((message) => (
            <div key={message.id} className={`message message-${message.role}`}>
              <span className="message-label">
                {message.role === 'user' ? 'You' : 'Assistant'}
              </span>
              {message.report ? (
                <DisasterReportView report={message.report} message={message.content} />
              ) : (
                message.content
              )}
            </div>
          ))
        )}
        {isLoading && (
          <div className="message message-assistant">
            <span className="message-label">Assistant</span>
            Thinking locally…
          </div>
        )}
      </div>
      {error && (
        <div className="assistant-error" role="alert">
          {error}
        </div>
      )}
      <form className="assistant-form" onSubmit={handleSubmit}>
        <label htmlFor="assistant-question" className="message-label">
          Question
        </label>
        <textarea
          id="assistant-question"
          value={question}
          onChange={(event) => setQuestion(event.target.value)}
          placeholder="Ask about the map or disaster monitoring…"
          disabled={isLoading}
          rows={3}
        />
        <div className="assistant-form-footer">
          <button type="button" onClick={onClear} disabled={isLoading}>
            Clear
          </button>
          <div>
            {isLoading && (
              <span className="loading-label">Local model is responding… </span>
            )}
            <button
              className="assistant-submit"
              type="submit"
              disabled={isLoading || !question.trim()}
            >
              Ask assistant
            </button>
          </div>
        </div>
      </form>
    </aside>
  );
}
