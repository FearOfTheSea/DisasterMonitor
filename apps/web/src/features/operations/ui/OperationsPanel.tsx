'use client';

import { FormEvent, useCallback, useEffect, useState } from 'react';

import {
  fetchCountryCatalogStatus,
  fetchEvidenceHistory,
  fetchProviderFreshness,
  recordOperatorReview,
  requestCountryCatalogUpdate,
} from '@/features/operations/api/operationsClient';
import type {
  CountryCatalogStatus,
  EvidenceSnapshot,
  ProviderFreshness,
} from '@/shared/types/operations';
import type {
  ActiveIncident,
  ActiveIncidentsSnapshot,
  CompoundHazardCorrelation,
} from '@/features/incidents/model/activeIncidents';
import { FindingsCenter } from '@/features/operations/ui/FindingsCenter';
import { IncidentWatches } from '@/features/operations/ui/IncidentWatches';

type OperationsPanelProps = {
  evidenceStateVersion?: string;
  onClose: () => void;
  onSelectWatchIncident: (incident: ActiveIncident) => void;
  activeIncidentsSnapshot?: ActiveIncidentsSnapshot;
  displayedIncidents?: readonly ActiveIncident[];
  displayedCorrelations?: readonly CompoundHazardCorrelation[];
};

function formatTime(value: string | null) {
  if (!value) return 'Never';
  const time = new Date(value);
  return Number.isNaN(time.getTime()) ? value : time.toLocaleString();
}

function formatDuration(seconds: number | null) {
  if (seconds === null) return 'Not available';
  if (seconds < 60) return `${seconds}s`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m`;
  const hours = Math.floor(minutes / 60);
  const remainingMinutes = minutes % 60;
  return remainingMinutes ? `${hours}h ${remainingMinutes}m` : `${hours}h`;
}

export function OperationsPanel({
  evidenceStateVersion,
  onClose,
  onSelectWatchIncident,
  activeIncidentsSnapshot,
  displayedIncidents = [],
  displayedCorrelations = [],
}: OperationsPanelProps) {
  const [providers, setProviders] = useState<ProviderFreshness[]>([]);
  const [history, setHistory] = useState<EvidenceSnapshot[]>([]);
  const [countryCatalog, setCountryCatalog] = useState<CountryCatalogStatus | null>(
    null,
  );
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [rationale, setRationale] = useState('');
  const [reviewStatus, setReviewStatus] = useState<string | null>(null);
  const [catalogUpdating, setCatalogUpdating] = useState(false);
  const [watchRefreshToken, setWatchRefreshToken] = useState(0);
  const handleWatchDataChange = useCallback(
    () => setWatchRefreshToken((current) => current + 1),
    [],
  );
  const orderedProviders = [...providers].sort((left, right) => {
    const healthOrder =
      Number(left.state === 'fresh') - Number(right.state === 'fresh');
    return healthOrder || left.source_id.localeCompare(right.source_id);
  });
  const providerCounts = providers.reduce<Record<ProviderFreshness['state'], number>>(
    (counts, provider) => ({ ...counts, [provider.state]: counts[provider.state] + 1 }),
    { fresh: 0, stale: 0, unavailable: 0, never_ingested: 0 },
  );

  const refresh = useCallback(async (signal?: AbortSignal) => {
    setLoading(true);
    setError(null);
    try {
      const [nextProviders, nextHistory, nextCatalog] = await Promise.all([
        fetchProviderFreshness(signal),
        fetchEvidenceHistory(signal),
        fetchCountryCatalogStatus(signal),
      ]);
      setProviders(nextProviders);
      setHistory(nextHistory);
      setCountryCatalog(nextCatalog);
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
      fetchCountryCatalogStatus(controller.signal),
    ])
      .then(([nextProviders, nextHistory, nextCatalog]) => {
        setProviders(nextProviders);
        setHistory(nextHistory);
        setCountryCatalog(nextCatalog);
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

  async function updateCountryCatalog() {
    setCatalogUpdating(true);
    setError(null);
    try {
      setCountryCatalog(await requestCountryCatalogUpdate());
    } catch (caught) {
      setError(
        caught instanceof Error ? caught.message : 'Country catalog update failed.',
      );
    } finally {
      setCatalogUpdating(false);
    }
  }

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
    <aside
      id="operations-panel"
      className="operations-panel"
      aria-label="Operational evidence status"
    >
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
        <FindingsCenter
          activeSnapshot={activeIncidentsSnapshot}
          displayedIncidents={displayedIncidents}
          displayedCorrelations={displayedCorrelations}
          onSelectIncident={onSelectWatchIncident}
          onWatchDataChange={handleWatchDataChange}
          refreshToken={watchRefreshToken}
        />
        <IncidentWatches
          onSelectIncident={onSelectWatchIncident}
          onDataChange={handleWatchDataChange}
          refreshToken={watchRefreshToken}
        />
        {loading && (
          <div className="operations-loading" role="status">
            <span className="loading-indicator" aria-hidden="true" />
            <span>Loading operational evidence…</span>
          </div>
        )}
        {error && (
          <div className="assistant-error" role="alert">
            {error}
          </div>
        )}
        <section className="operations-section">
          <div className="operations-heading">
            <h3>Country catalog automation</h3>
            <button
              type="button"
              onClick={() => void updateCountryCatalog()}
              disabled={loading || catalogUpdating}
            >
              {catalogUpdating ? 'Updating countries…' : 'Update countries now'}
            </button>
          </div>
          {countryCatalog ? (
            <div className="catalog-status">
              <div>
                <strong>{countryCatalog.country_count} active countries</strong>
                <span className={`freshness freshness-${countryCatalog.state}`}>
                  {countryCatalog.state.replaceAll('_', ' ')}
                </span>
              </div>
              <small>Version: {countryCatalog.active_version}</small>
              <small>
                Last successful update: {formatTime(countryCatalog.last_success_at)}
              </small>
              <small>
                Next automatic attempt: {formatTime(countryCatalog.next_scheduled_at)}
              </small>
              <p role="status">{countryCatalog.message}</p>
              {countryCatalog.failure_code && (
                <small>Failure code: {countryCatalog.failure_code}</small>
              )}
              {countryCatalog.sources.map((source) => (
                <small key={source.source_id}>
                  {source.source_id}: {source.version}
                </small>
              ))}
            </div>
          ) : (
            !loading && <p>Country catalog status is unavailable.</p>
          )}
        </section>
        <section className="operations-section">
          <div className="operations-heading">
            <h3>Source health &amp; coverage</h3>
            <button
              type="button"
              onClick={() => void refresh()}
              disabled={loading}
              aria-label="Refresh source health"
            >
              Refresh
            </button>
          </div>
          {providers.length > 0 && (
            <div className="provider-summary" aria-label="Source health summary">
              <span>Sources {providers.length}</span>
              <span className="summary-fresh">Fresh {providerCounts.fresh}</span>
              <span className="summary-stale">Stale {providerCounts.stale}</span>
              <span className="summary-unavailable">
                Unavailable {providerCounts.unavailable}
              </span>
              <span className="summary-never">
                Never ingested {providerCounts.never_ingested}
              </span>
            </div>
          )}
          <div className="provider-grid">
            {orderedProviders.map((provider) => (
              <article key={provider.source_id} className="provider-status">
                <div>
                  <strong data-testid="provider-source">{provider.source_id}</strong>
                  <span className={`freshness freshness-${provider.state}`}>
                    Status: {provider.state.replaceAll('_', ' ')}
                  </span>
                </div>
                <small>Evidence time: {formatTime(provider.effective_at)}</small>
                <small>Evidence age: {formatDuration(provider.age_seconds)}</small>
                <small>Last attempt: {formatTime(provider.last_attempt_at)}</small>
                <small>Last success: {formatTime(provider.last_success_at)}</small>
                <small>
                  Expected interval:{' '}
                  {formatDuration(provider.expected_freshness_seconds)}
                </small>
                <small>Consecutive failures: {provider.consecutive_failures}</small>
                {provider.latest_error_code && (
                  <small>Latest error: {provider.latest_error_code}</small>
                )}
              </article>
            ))}
            {!loading && providers.length === 0 && (
              <p className="provider-empty">
                No provider freshness records are available.
              </p>
            )}
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
