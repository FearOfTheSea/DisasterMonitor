'use client';

import { FormEvent, useState } from 'react';

import type {
  AssistantReport,
  ConversationMessage,
  ConversationStatus,
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
        <p>Powered by your local Qwen model through Ollama.</p>
      </header>
      <div className="availability-note">
        Source-backed current disaster reports are available for recognized requests;
        unsupported coverage is reported explicitly. Other live datasets remain
        unconnected.
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
