'use client';

import { FormEvent, useCallback, useEffect, useState } from 'react';

import {
  fetchEvidenceHistory,
  fetchProviderFreshness,
  recordOperatorReview,
} from '@/features/operations/api/operationsClient';
import type { EvidenceSnapshot, ProviderFreshness } from '@/shared/types/operations';

type OperationsPanelProps = {
  evidenceStateVersion?: string;
  onClose: () => void;
};

function formatTime(value: string | null) {
  if (!value) return 'Never';
  const time = new Date(value);
  return Number.isNaN(time.getTime()) ? value : time.toLocaleString();
}

export function OperationsPanel({
  evidenceStateVersion,
  onClose,
}: OperationsPanelProps) {
  const [providers, setProviders] = useState<ProviderFreshness[]>([]);
  const [history, setHistory] = useState<EvidenceSnapshot[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [rationale, setRationale] = useState('');
  const [reviewStatus, setReviewStatus] = useState<string | null>(null);

  const refresh = useCallback(async (signal?: AbortSignal) => {
    setLoading(true);
    setError(null);
    try {
      const [nextProviders, nextHistory] = await Promise.all([
        fetchProviderFreshness(signal),
        fetchEvidenceHistory(signal),
      ]);
      setProviders(nextProviders);
      setHistory(nextHistory);
    } catch (caught) {
      if (!(caught instanceof DOMException && caught.name === 'AbortError')) {
        setError(caught instanceof Error ? caught.message : 'Operations data failed.');
      }
    } finally {
      if (!signal?.aborted) setLoading(false);
    }
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    void Promise.all([
      fetchProviderFreshness(controller.signal),
      fetchEvidenceHistory(controller.signal),
    ])
      .then(([nextProviders, nextHistory]) => {
        setProviders(nextProviders);
        setHistory(nextHistory);
      })
      .catch((caught) => {
        if (!(caught instanceof DOMException && caught.name === 'AbortError')) {
          setError(
            caught instanceof Error ? caught.message : 'Operations data failed.',
          );
        }
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, []);

  async function submitReview(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!evidenceStateVersion || !rationale.trim()) return;
    setReviewStatus('Recording review…');
    try {
      const result = await recordOperatorReview(evidenceStateVersion, rationale.trim());
      setReviewStatus(`Review recorded for ${result.operator_id}.`);
      setRationale('');
    } catch (caught) {
      setReviewStatus(
        caught instanceof Error ? caught.message : 'The review could not be recorded.',
      );
    }
  }

  return (
    <aside className="operations-panel" aria-label="Operational evidence status">
      <header className="operations-panel-header">
        <div>
          <h2>Evidence operations</h2>
          <p>Provider freshness, retained snapshots, and attributable review.</p>
        </div>
        <button type="button" onClick={onClose} aria-label="Close operations panel">
          Close
        </button>
      </header>
      <div className="operations-scroll">
        {loading && <p role="status">Loading operational evidence…</p>}
        {error && <div className="assistant-error">{error}</div>}
        <section className="operations-section">
          <div className="operations-heading">
            <h3>Provider freshness</h3>
            <button type="button" onClick={() => void refresh()} disabled={loading}>
              Refresh
            </button>
          </div>
          <div className="provider-grid">
            {providers.map((provider) => (
              <article key={provider.source_id} className="provider-status">
                <div>
                  <strong>{provider.source_id}</strong>
                  <span className={`freshness freshness-${provider.state}`}>
                    {provider.state.replaceAll('_', ' ')}
                  </span>
                </div>
                <small>Evidence time: {formatTime(provider.effective_at)}</small>
                {provider.latest_error_code && (
                  <small>Latest error: {provider.latest_error_code}</small>
                )}
              </article>
            ))}
          </div>
        </section>
        <section className="operations-section">
          <h3>Latest immutable snapshots</h3>
          {history.length === 0 ? (
            <p>No source snapshots have been admitted in this runtime.</p>
          ) : (
            <div className="snapshot-list">
              {history.map((snapshot) => (
                <article key={snapshot.snapshot_id} className="snapshot-card">
                  <div>
                    <strong>{snapshot.source_id}</strong>
                    <span>
                      {snapshot.content_available ? 'Content retained' : 'Tombstone'}
                    </span>
                  </div>
                  <small>{formatTime(snapshot.effective_at)}</small>
                  <code>{snapshot.payload_sha256}</code>
                  <small>Rights record: {snapshot.rights_id}</small>
                  {snapshot.content_deletion_reason && (
                    <small>Deletion reason: {snapshot.content_deletion_reason}</small>
                  )}
                </article>
              ))}
            </div>
          )}
        </section>
        <section className="operations-section">
          <h3>Record bounded review</h3>
          <p>
            This records that an evidence state was reviewed. It does not issue a public
            warning or operational command.
          </p>
          {evidenceStateVersion ? (
            <form className="review-form" onSubmit={submitReview}>
              <small>State: {evidenceStateVersion}</small>
              <textarea
                aria-label="Review rationale"
                value={rationale}
                onChange={(event) => setRationale(event.target.value)}
                maxLength={2000}
                rows={3}
                placeholder="Describe the evidence and freshness checked."
              />
              <button type="submit" disabled={!rationale.trim()}>
                Record review
              </button>
            </form>
          ) : (
            <p>Run an evidence-backed investigation before recording a review.</p>
          )}
          {reviewStatus && <p role="status">{reviewStatus}</p>}
        </section>
      </div>
    </aside>
  );
}
