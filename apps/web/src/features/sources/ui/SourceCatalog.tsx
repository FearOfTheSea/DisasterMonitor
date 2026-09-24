'use client';

import { useCallback, useEffect, useRef, useState } from 'react';

import { fetchSourceCatalog } from '@/features/sources/api/sourceCatalogClient';
import type { SourceCatalogSnapshot } from '@/features/sources/model/sourceCatalog';
import {
  createRefreshController,
  REFRESH_POLICIES,
  type RefreshController,
} from '@/shared/model/refreshPolicy';
import {
  readOfflineSnapshot,
  writeOfflineSnapshot,
} from '@/shared/model/offlineSnapshot';
import { PanelCloseButton } from '@/shared/ui/PanelCloseButton';

type SourceCatalogProps = {
  onClose: () => void;
};

const SOURCE_CATALOG_CACHE_KEY = 'disaster-monitor:pwa:source-catalog:v1';

function isSourceCatalogSnapshot(value: unknown): value is SourceCatalogSnapshot {
  return (
    typeof value === 'object' &&
    value !== null &&
    typeof (value as SourceCatalogSnapshot).catalog_version === 'string' &&
    Array.isArray((value as SourceCatalogSnapshot).sources)
  );
}

function label(value: string): string {
  return value.replaceAll('_', ' ');
}

export function SourceCatalog({ onClose }: SourceCatalogProps) {
  const [snapshot, setSnapshot] = useState<SourceCatalogSnapshot>();
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string>();
  const [offlineCachedAt, setOfflineCachedAt] = useState<string>();
  const [search, setSearch] = useState('');
  const [hazard, setHazard] = useState('');
  const [role, setRole] = useState('');
  const [selectedSourceId, setSelectedSourceId] = useState<string>();
  const refreshController = useRef<RefreshController | undefined>(undefined);
  const load = useCallback(async (signal: AbortSignal) => {
    try {
      const next = await fetchSourceCatalog(signal);
      if (signal.aborted) return;
      setSnapshot(next);
      writeOfflineSnapshot(SOURCE_CATALOG_CACHE_KEY, next);
      setOfflineCachedAt(undefined);
      setError(undefined);
    } catch (caught) {
      if (signal.aborted) return;
      const cached = readOfflineSnapshot(
        SOURCE_CATALOG_CACHE_KEY,
        isSourceCatalogSnapshot,
      );
      if (cached) {
        setSnapshot(cached.value);
        setOfflineCachedAt(cached.cachedAt);
        setError(undefined);
      } else {
        setError(
          caught instanceof Error ? caught.message : 'Source Catalog could not load.',
        );
      }
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

  const sources = (snapshot?.sources ?? []).filter((source) => {
    const query = search.trim().toLocaleLowerCase();
    return (
      (!query ||
        [source.provider, source.publisher, source.coverage_description].some((value) =>
          value.toLocaleLowerCase().includes(query),
        )) &&
      (!hazard || source.supported_disasters.includes(hazard)) &&
      (!role || source.information_roles.includes(role))
    );
  });
  const hazards = [
    ...new Set(snapshot?.sources.flatMap((source) => source.supported_disasters) ?? []),
  ].sort();
  const roles = [
    ...new Set(snapshot?.sources.flatMap((source) => source.information_roles) ?? []),
  ].sort();

  return (
    <aside
      id="source-catalog-panel"
      className="source-catalog-panel"
      aria-label="Source Catalog"
    >
      <header className="source-catalog-header">
        <div>
          <h2>Sources</h2>
          <p>See where information comes from and when it was last checked.</p>
        </div>
        <PanelCloseButton label="Close Source Catalog" onClick={onClose} />
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
        {offlineCachedAt ? (
          <p role="status">
            Offline · read-only · stale source catalog cached{' '}
            {new Date(offlineCachedAt).toLocaleString()}.
          </p>
        ) : null}
        <p className="source-catalog-boundary">
          This catalog is informational. It cannot enable, disable, or reprioritize a
          provider.
        </p>
        <div className="source-directory-filters">
          <label>
            Search sources
            <input
              type="search"
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder="Publisher or coverage"
            />
          </label>
          <label>
            Hazard
            <select value={hazard} onChange={(event) => setHazard(event.target.value)}>
              <option value="">All hazards</option>
              {hazards.map((value) => (
                <option key={value} value={value}>
                  {label(value)}
                </option>
              ))}
            </select>
          </label>
          <label>
            Role
            <select value={role} onChange={(event) => setRole(event.target.value)}>
              <option value="">All roles</option>
              {roles.map((value) => (
                <option key={value} value={value}>
                  {label(value)}
                </option>
              ))}
            </select>
          </label>
        </div>
        {snapshot && sources.length === 0 ? (
          <p>No sources match these directory filters.</p>
        ) : null}
        <div className="source-catalog-list">
          {sources.map((source) => (
            <article className="source-catalog-card" key={source.source_id}>
              <header>
                <div>
                  <h3>{source.provider}</h3>
                  <p>{source.publisher}</p>
                </div>
                <span>
                  Configuration: {label(source.operational_state.availability)}
                </span>
              </header>
              <p className="source-directory-summary">
                {source.information_roles.map(label).join(', ') || 'Role unspecified'} ·{' '}
                {source.coverage_description}
              </p>
              <button
                type="button"
                aria-expanded={selectedSourceId === source.source_id}
                onClick={() =>
                  setSelectedSourceId((current) =>
                    current === source.source_id ? undefined : source.source_id,
                  )
                }
              >
                View provenance and limitations
              </button>
              {selectedSourceId === source.source_id && (
                <>
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
                      <dd>
                        {source.information_roles.map(label).join(', ') || 'None'}
                      </dd>
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
                      <dt>Access / rights</dt>
                      <dd>
                        {source.access_model
                          ? label(source.access_model)
                          : 'Not recorded'}
                        {source.license_name ? ` · ${source.license_name}` : ''}
                        {source.rights_id ? ` · ${source.rights_id}` : ''}
                        {source.rights_reviewed_at
                          ? ` · reviewed ${source.rights_reviewed_at}`
                          : ''}
                      </dd>
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
                </>
              )}
            </article>
          ))}
        </div>
      </div>
    </aside>
  );
}
