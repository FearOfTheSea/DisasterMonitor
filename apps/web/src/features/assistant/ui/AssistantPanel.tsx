'use client';

import { FormEvent, useEffect, useRef, useState } from 'react';

import { OperatorActionCard } from '@/features/assistant/ui/OperatorActionCard';
import { DisasterReportView } from '@/features/assistant/ui/AssistantEvidenceViews';
import type {
  ConversationMessage,
  ConversationSummary,
  ConversationStatus,
} from '@/shared/types/assistant';

type AssistantPanelProps = {
  conversationId?: string | null;
  conversations?: ConversationSummary[];
  messages: ConversationMessage[];
  status: ConversationStatus;
  error: string | null;
  onSubmit: (question: string) => Promise<void>;
  onClear: () => void;
  onNewConversation?: () => void;
  onSelectConversation?: (conversationId: string | null) => void | Promise<void>;
  onDeleteConversation?: (conversationId: string) => void | Promise<void>;
  onWatchReady?: () => void;
};

export function AssistantPanel({
  conversationId = null,
  conversations = [],
  messages,
  status,
  error,
  onSubmit,
  onClear,
  onNewConversation,
  onSelectConversation,
  onDeleteConversation,
  onWatchReady,
}: AssistantPanelProps) {
  const [question, setQuestion] = useState('');
  const composerRef = useRef<HTMLTextAreaElement>(null);
  const previousConversationId = useRef(conversationId);
  const isLoading = status === 'loading';

  useEffect(() => {
    if (previousConversationId.current && conversationId === null) {
      composerRef.current?.scrollIntoView?.({ block: 'nearest' });
      composerRef.current?.focus();
    }
    previousConversationId.current = conversationId;
  }, [conversationId]);

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
    <aside
      id="assistant-panel"
      className="assistant-panel"
      aria-label="Disaster Monitor assistant"
    >
      <header className="assistant-panel-header">
        <div className="panel-heading">
          <h2>Map assistant</h2>
          <p>Agent-first routing with local Qwen and trusted source tools.</p>
        </div>
        <div className="conversation-controls">
          <label htmlFor="assistant-conversation">Conversation</label>
          <select
            id="assistant-conversation"
            value={conversationId ?? ''}
            onChange={(event) => onSelectConversation?.(event.target.value || null)}
            disabled={isLoading}
          >
            <option value="">New conversation</option>
            {conversations.map((conversation) => (
              <option
                key={conversation.conversation_id}
                value={conversation.conversation_id}
              >
                {conversation.preview || 'Untitled conversation'}
              </option>
            ))}
          </select>
          {conversationId && onDeleteConversation && (
            <button
              type="button"
              onClick={() => void onDeleteConversation(conversationId)}
              disabled={isLoading}
            >
              Delete conversation
            </button>
          )}
        </div>
      </header>
      <div className="availability-note">
        Source-backed current disaster reports are available for recognized requests;
        unsupported coverage is reported explicitly. Selected events can include bounded
        source-photo previews when date, disaster, geography, credit, and source policy
        agree. Operator-supplied imagery remains a separate analytical path.
      </div>
      <div className="message-list" aria-live="polite">
        {messages.length === 0 ? (
          <div className="empty-state">
            <svg viewBox="0 0 24 24" aria-hidden="true">
              <path d="M19 14.5a4 4 0 0 1-4 4H9l-5 3v-7a4 4 0 0 1-1-2.7V7a4 4 0 0 1 4-4h8a4 4 0 0 1 4 4z" />
            </svg>
            <strong>No messages yet</strong>
            <p>Your conversation will appear here.</p>
          </div>
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
              {message.operatorActions?.map((action) =>
                action.action_type === 'create_incident_watch' ? (
                  <OperatorActionCard
                    key={`${message.id}:${action.action_id}`}
                    action={action}
                    onWatchReady={onWatchReady}
                  />
                ) : null,
              )}
            </div>
          ))
        )}
        {isLoading && (
          <div className="message message-assistant message-loading" role="status">
            <span className="loading-indicator" aria-hidden="true" />
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
          ref={composerRef}
          value={question}
          onChange={(event) => setQuestion(event.target.value)}
          placeholder="Ask about the map or disaster monitoring…"
          disabled={isLoading}
          rows={3}
        />
        <div className="assistant-form-footer">
          <button
            type="button"
            onClick={onNewConversation ?? onClear}
            disabled={isLoading}
          >
            New conversation
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
