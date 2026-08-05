'use client';

import { FormEvent, useState } from 'react';

import type { ConversationMessage, ConversationStatus } from '@/shared/types/assistant';

type AssistantPanelProps = {
  messages: ConversationMessage[];
  status: ConversationStatus;
  error: string | null;
  onSubmit: (question: string) => Promise<void>;
  onClear: () => void;
};

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
        External data is not connected yet. The assistant cannot see live weather,
        flood, satellite, or geocoding results.
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
              {message.content}
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
