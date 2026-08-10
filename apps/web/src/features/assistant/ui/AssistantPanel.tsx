'use client';

import { FormEvent, useState } from 'react';

import type {
  AssistantReport,
  CommonOperationalPicture,
  ConversationMessage,
  ConversationStatus,
  MultimodalEvidenceState,
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
          ).map((warning) => (
            <p key={warning}>{warning}</p>
          ))}
        </div>
      )}
      {report.selectedEvent && (
        <div className="report-event">
          <strong>{report.selectedEvent.location}</strong>
          <span>
            {formatTime(report.selectedEvent.event_time)}
            {report.selectedEvent.magnitude !== undefined
              ? ` · M${report.selectedEvent.magnitude}`
              : ''}
          </span>
        </div>
      )}
      <div className="report-sections">
        {report.sections.map((section) => (
          <section key={section.title}>
            <h3>{section.title}</h3>
            <p>{section.content}</p>
          </section>
        ))}
      </div>
      {report.multimodal && <VisualEvidenceView state={report.multimodal} />}
      {report.commonOperationalPicture && (
        <CopSummary cop={report.commonOperationalPicture} />
      )}
      {report.sources.length > 0 && (
        <div className="report-sources">
          <h3>Source timestamps</h3>
          {report.sources.map((source) => (
            <a
              key={source.canonical_url}
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
            </a>
          ))}
        </div>
      )}
      {report.investigation && (
        <details className="investigation-summary">
          <summary>Investigation details</summary>
          <p>
            Status: <strong>{report.investigation.status}</strong>
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
          {report.investigation.actions.length > 0 && (
            <>
              <h3>Completed actions</h3>
              <ul>
                {report.investigation.actions.map((action) => (
                  <li key={action}>{action}</li>
                ))}
              </ul>
            </>
          )}
          {report.investigation.capability_gaps.length > 0 && (
            <>
              <h3>Capability gaps</h3>
              <ul>
                {report.investigation.capability_gaps.map((gap) => (
                  <li key={gap}>{gap}</li>
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
        unsupported coverage is reported explicitly. Bounded operator-supplied imagery
        with explicit event metadata can produce analytical overlays through the API;
        automatic imagery retrieval and live satellite feeds remain unconnected.
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
