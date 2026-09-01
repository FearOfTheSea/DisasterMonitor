'use client';

import { useCallback, useEffect, useRef, useState } from 'react';

import { fetchSourceCatalog } from '@/features/sources/api/sourceCatalogClient';
import type { SourceCatalogSnapshot } from '@/features/sources/model/sourceCatalog';
import {
  createRefreshController,
  REFRESH_POLICIES,
  type RefreshController,
} from '@/shared/model/refreshPolicy';

type SourceCatalogProps = {
  onClose: () => void;
};

function label(value: string): string {
  return value.replaceAll('_', ' ');
}

export function SourceCatalog({ onClose }: SourceCatalogProps) {
  const [snapshot, setSnapshot] = useState<SourceCatalogSnapshot>();
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string>();
  const refreshController = useRef<RefreshController | undefined>(undefined);
  const load = useCallback(async (signal: AbortSignal) => {
    try {
      const next = await fetchSourceCatalog(signal);
      if (signal.aborted) return;
      setSnapshot(next);
      setError(undefined);
    } catch (caught) {
      if (signal.aborted) return;
      setError(
        caught instanceof Error ? caught.message : 'Source Catalog could not load.',
      );
    } finally {
      if (!signal.aborted) setLoading(false);
    }
  }, []);

  useEffect(() => {
    const controller = createRefreshController(
      REFRESH_POLICIES['source-catalog'],
      load,
      document,
    );
    refreshController.current = controller;
    controller.start();
    return () => {
      controller.stop();
      refreshController.current = undefined;
    };
  }, [load]);

  return (
    <aside
      id="source-catalog-panel"
      className="source-catalog-panel"
      aria-label="Source Catalog"
    >
      <header className="source-catalog-header">
        <div>
          <h2>Source Catalog</h2>
          <p>Maintained authority metadata with separately labelled runtime state.</p>
        </div>
        <button type="button" onClick={onClose} aria-label="Close Source Catalog">
          Close
        </button>
      </header>
      <div className="source-catalog-scroll">
        <div className="source-catalog-summary">
          <span>Catalog version {snapshot?.catalog_version ?? 'unavailable'}</span>
          <button
            type="button"
            disabled={loading}
            onClick={() => void refreshController.current?.refreshNow()}
          >
            Refresh metadata
          </button>
        </div>
        {loading && !snapshot ? <p role="status">Loading Source Catalog…</p> : null}
        {error ? <p role="alert">{error}</p> : null}
        <p className="source-catalog-boundary">
          This catalog is informational. It cannot enable, disable, or reprioritize a
          provider.
        </p>
        <div className="source-catalog-list">
          {snapshot?.sources.map((source) => (
            <article className="source-catalog-card" key={source.source_id}>
              <header>
                <div>
                  <h3>{source.provider}</h3>
                  <p>{source.publisher}</p>
                </div>
                <span>{label(source.operational_state.availability)}</span>
              </header>
              <dl>
                <div>
                  <dt>Authority</dt>
                  <dd>
                    {label(source.authority)}
                    {source.operational_state.provider_tier
                      ? ` · ${source.operational_state.provider_tier} tier`
                      : ''}
                  </dd>
                </div>
                <div>
                  <dt>Information roles</dt>
                  <dd>{source.information_roles.map(label).join(', ') || 'None'}</dd>
                </div>
                <div>
                  <dt>Physical disaster types</dt>
                  <dd>
                    {source.supported_disasters.length > 0
                      ? source.supported_disasters.map(label).join(', ')
                      : 'No physical disaster type; separate warning or context artifact'}
                  </dd>
                </div>
                <div>
                  <dt>Coverage</dt>
                  <dd>{source.coverage_description}</dd>
                </div>
                <div>
                  <dt>Runtime state</dt>
                  <dd>
                    {source.operational_state.registered
                      ? 'Registered'
                      : 'Not registered'}{' '}
                    ·{' '}
                    {source.operational_state.configured
                      ? 'Configured'
                      : 'Unconfigured'}
                    . {source.operational_state.availability_detail}
                  </dd>
                </div>
                <div>
                  <dt>Freshness / publication</dt>
                  <dd>{source.freshness_semantics}</dd>
                </div>
                <div>
                  <dt>Stale threshold</dt>
                  <dd>
                    {source.stale_threshold_seconds === null
                      ? 'Stale threshold: unspecified'
                      : `${source.stale_threshold_seconds} seconds`}
                  </dd>
                </div>
                {source.documentation_path ? (
                  <div>
                    <dt>Source documentation</dt>
                    <dd>{source.documentation_path}</dd>
                  </div>
                ) : null}
              </dl>
              <details>
                <summary>Limitations and attribution</summary>
                <p>{source.attribution}</p>
                <ul>
                  {source.limitations.map((limitation) => (
                    <li key={limitation}>{limitation}</li>
                  ))}
                </ul>
              </details>
            </article>
          ))}
        </div>
      </div>
    </aside>
  );
}
