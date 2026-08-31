'use client';

import { FormEvent, useCallback, useEffect, useState } from 'react';

import {
  createIncidentWatch,
  deleteIncidentWatch,
  fetchIncidentWatches,
  fetchIncidentWatchTimeline,
  markIncidentWatchTimelineRead,
  setIncidentWatchEnabled,
} from '@/features/operations/api/incidentWatches';
import type {
  IncidentWatch,
  IncidentWatchChange,
  IncidentWatchCoverageState,
  IncidentWatchEvent,
} from '@/features/operations/model/incidentWatch';
import type { DisasterType } from '@/features/incidents/model/activeIncidents';

type IncidentWatchesProps = {
  onSelectIncident: (incident: IncidentWatchEvent) => void;
};

const DISASTERS: { value: DisasterType; label: string }[] = [
  { value: 'earthquake', label: 'Earthquake' },
  { value: 'flood', label: 'Flood' },
  { value: 'wildfire', label: 'Wildfire' },
  { value: 'landslide', label: 'Landslide' },
  { value: 'tropical_cyclone', label: 'Tropical cyclone' },
  { value: 'volcanic_eruption', label: 'Volcanic eruption' },
];

const COVERAGE_LABELS: Record<IncidentWatchCoverageState, string> = {
  events_found: 'Events found',
  no_matching_records: 'No matching records',
  stale: 'Stale evidence',
  degraded: 'Degraded',
  unavailable: 'Unavailable',
};

function formatTime(value: string | null): string {
  if (!value) return 'Never';
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleString();
}

function watchLabel(watch: IncidentWatch): string {
  return watch.scope.country_name ?? 'Worldwide';
}

function disasterLabel(disaster: DisasterType): string {
  return DISASTERS.find((item) => item.value === disaster)?.label ?? disaster;
}

function hasMappableGeometry(incident: IncidentWatchEvent | null): boolean {
  if (!incident?.geometry || incident.geometry.kind === 'descriptive') return false;
  if (incident.geometry.kind === 'point') {
    return incident.geometry.coordinates.length === 1;
  }
  if (incident.geometry.kind === 'track') {
    return incident.geometry.coordinates.length >= 2;
  }
  return incident.geometry.coordinates.length >= 3;
}

export function IncidentWatches({ onSelectIncident }: IncidentWatchesProps) {
  const [watches, setWatches] = useState<IncidentWatch[]>([]);
  const [selectedWatchId, setSelectedWatchId] = useState<string>();
  const [timeline, setTimeline] = useState<IncidentWatchChange[]>([]);
  const [loading, setLoading] = useState(true);
  const [timelineLoading, setTimelineLoading] = useState(false);
  const [error, setError] = useState<string>();
  const [disaster, setDisaster] = useState<DisasterType>('earthquake');
  const [scopeKind, setScopeKind] = useState<'country' | 'worldwide'>('country');
  const [country, setCountry] = useState('');
  const [interval, setInterval] = useState(900);
  const [saving, setSaving] = useState(false);

  const loadWatches = useCallback(async (signal?: AbortSignal) => {
    setLoading(true);
    setError(undefined);
    try {
      setWatches(await fetchIncidentWatches(signal));
    } catch (caught) {
      if (!(caught instanceof DOMException && caught.name === 'AbortError')) {
        setError(caught instanceof Error ? caught.message : 'Incident watches failed.');
      }
    } finally {
      if (!signal?.aborted) setLoading(false);
    }
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    void fetchIncidentWatches(controller.signal)
      .then(setWatches)
      .catch((caught: unknown) => {
        if (!(caught instanceof DOMException && caught.name === 'AbortError')) {
          setError(
            caught instanceof Error ? caught.message : 'Incident watches failed.',
          );
        }
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, []);

  async function submitCreate(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (scopeKind === 'country' && !country.trim()) return;
    setSaving(true);
    setError(undefined);
    try {
      const created = await createIncidentWatch({
        disaster,
        scope:
          scopeKind === 'worldwide'
            ? { kind: 'worldwide' }
            : { kind: 'country', country: country.trim() },
        refresh_interval_seconds: interval,
      });
      setWatches((current) => [created, ...current]);
      setCountry('');
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Watch creation failed.');
    } finally {
      setSaving(false);
    }
  }

  async function showTimeline(watch: IncidentWatch) {
    setSelectedWatchId(watch.watch_id);
    setTimelineLoading(true);
    setError(undefined);
    try {
      setTimeline(await fetchIncidentWatchTimeline(watch.watch_id));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Watch timeline failed.');
      setTimeline([]);
    } finally {
      setTimelineLoading(false);
    }
  }

  async function toggleWatch(watch: IncidentWatch) {
    setError(undefined);
    try {
      const updated = await setIncidentWatchEnabled(watch.watch_id, !watch.enabled);
      setWatches((current) =>
        current.map((item) => (item.watch_id === updated.watch_id ? updated : item)),
      );
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Watch update failed.');
    }
  }

  async function removeWatch(watch: IncidentWatch) {
    setError(undefined);
    try {
      await deleteIncidentWatch(watch.watch_id);
      setWatches((current) =>
        current.filter((item) => item.watch_id !== watch.watch_id),
      );
      if (selectedWatchId === watch.watch_id) {
        setSelectedWatchId(undefined);
        setTimeline([]);
      }
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Watch deletion failed.');
    }
  }

  async function markRead() {
    if (!selectedWatchId) return;
    const unreadIds = timeline
      .filter((item) => item.read_at === null)
      .map((item) => item.change_id);
    if (unreadIds.length === 0) return;
    setError(undefined);
    try {
      const result = await markIncidentWatchTimelineRead(selectedWatchId, unreadIds);
      const readAt = new Date().toISOString();
      setTimeline((current) =>
        current.map((item) =>
          unreadIds.includes(item.change_id) ? { ...item, read_at: readAt } : item,
        ),
      );
      setWatches((current) =>
        current.map((item) =>
          item.watch_id === selectedWatchId
            ? { ...item, unread_change_count: result.unread_change_count }
            : item,
        ),
      );
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Timeline update failed.');
    }
  }

  const selectedWatch = watches.find((item) => item.watch_id === selectedWatchId);

  return (
    <section className="incident-watches" aria-labelledby="incident-watches-heading">
      <div className="operations-heading">
        <div>
          <h3 id="incident-watches-heading">Incident watches</h3>
          <p>Bounded scheduled monitoring; not complete global surveillance.</p>
        </div>
        <button type="button" onClick={() => void loadWatches()} disabled={loading}>
          Refresh watches
        </button>
      </div>
      <form className="incident-watch-create" onSubmit={submitCreate}>
        <label>
          <span>Watch disaster</span>
          <select
            aria-label="Watch disaster"
            value={disaster}
            onChange={(event) => setDisaster(event.target.value as DisasterType)}
          >
            {DISASTERS.map((item) => (
              <option key={item.value} value={item.value}>
                {item.label}
              </option>
            ))}
          </select>
        </label>
        <label>
          <span>Watch scope</span>
          <select
            aria-label="Watch scope"
            value={scopeKind}
            onChange={(event) =>
              setScopeKind(event.target.value as 'country' | 'worldwide')
            }
          >
            <option value="country">Named country</option>
            <option value="worldwide">Worldwide</option>
          </select>
        </label>
        {scopeKind === 'country' ? (
          <label>
            <span>Country name</span>
            <input
              aria-label="Country name"
              value={country}
              maxLength={200}
              onChange={(event) => setCountry(event.target.value)}
              placeholder="Vietnam"
            />
          </label>
        ) : null}
        <label>
          <span>Refresh interval</span>
          <select
            aria-label="Refresh interval"
            value={interval}
            onChange={(event) => setInterval(Number(event.target.value))}
          >
            <option value="900">15 minutes</option>
            <option value="1800">30 minutes</option>
            <option value="3600">1 hour</option>
            <option value="21600">6 hours</option>
            <option value="86400">24 hours</option>
          </select>
        </label>
        <button
          type="submit"
          disabled={saving || (scopeKind === 'country' && !country.trim())}
        >
          {saving ? 'Creating…' : 'Create watch'}
        </button>
      </form>
      {loading ? (
        <div className="operations-loading" role="status">
          <span className="loading-indicator" aria-hidden="true" />
          <span>Loading incident watches…</span>
        </div>
      ) : null}
      {error ? (
        <div className="assistant-error" role="alert">
          {error}
        </div>
      ) : null}
      {!loading && watches.length === 0 ? (
        <div className="incident-watch-empty">
          <strong>No incident watches have been created.</strong>
          <p>Create one bounded monitoring scope to begin scheduled source checks.</p>
        </div>
      ) : null}
      <div className="incident-watch-list">
        {watches.map((watch) => {
          const label = watchLabel(watch);
          return (
            <article key={watch.watch_id} className="incident-watch-card">
              <div className="incident-watch-card-heading">
                <div>
                  <strong>{label}</strong>
                  <span>{disasterLabel(watch.disaster)}</span>
                </div>
                <span className={watch.enabled ? 'watch-enabled' : 'watch-disabled'}>
                  {watch.enabled ? 'Enabled' : 'Disabled'}
                </span>
              </div>
              <div className="incident-watch-meta">
                <span>
                  {watch.coverage_state
                    ? COVERAGE_LABELS[watch.coverage_state]
                    : 'Not checked'}
                </span>
                <span>{watch.unread_change_count} unread</span>
                <span>Last checked: {formatTime(watch.last_checked_at)}</span>
              </div>
              <div className="incident-watch-actions">
                <button
                  type="button"
                  onClick={() => void showTimeline(watch)}
                  aria-label={`Show timeline for ${label}`}
                >
                  Timeline
                </button>
                <button
                  type="button"
                  onClick={() => void toggleWatch(watch)}
                  aria-label={`${watch.enabled ? 'Disable' : 'Enable'} ${label} watch`}
                >
                  {watch.enabled ? 'Disable' : 'Enable'}
                </button>
                <button
                  type="button"
                  onClick={() => void removeWatch(watch)}
                  aria-label={`Delete ${label} watch`}
                >
                  Delete
                </button>
              </div>
            </article>
          );
        })}
      </div>
      {selectedWatch ? (
        <section className="incident-watch-timeline" aria-label="Watch timeline">
          <div className="operations-heading">
            <h4>{watchLabel(selectedWatch)} timeline</h4>
            <button
              type="button"
              onClick={() => void markRead()}
              disabled={!timeline.some((item) => item.read_at === null)}
            >
              Mark timeline read
            </button>
          </div>
          {timelineLoading ? <p role="status">Loading watch timeline…</p> : null}
          {!timelineLoading && timeline.length === 0 ? (
            <p>No meaningful source-backed changes have been recorded.</p>
          ) : null}
          <div className="incident-watch-change-list">
            {timeline.map((change) => (
              <article
                key={change.change_id}
                className={`incident-watch-change${change.read_at ? '' : ' incident-watch-change-unread'}`}
              >
                <div>
                  <strong>{change.summary}</strong>
                  <span>{change.read_at ? 'Read' : 'Unread'}</span>
                </div>
                <small>{formatTime(change.created_at)}</small>
                <p>{change.detail}</p>
                {change.source_ids.length > 0 ? (
                  <small>Sources: {change.source_ids.join(', ')}</small>
                ) : null}
                {change.incident ? (
                  <a
                    href={change.incident.source.canonical_url}
                    target="_blank"
                    rel="noreferrer"
                  >
                    {change.incident.source.publisher}
                  </a>
                ) : null}
                {hasMappableGeometry(change.incident) && change.incident ? (
                  <button
                    type="button"
                    onClick={() =>
                      onSelectIncident(change.incident as IncidentWatchEvent)
                    }
                    aria-label={`Focus ${change.incident.location} on map`}
                  >
                    Focus on map
                  </button>
                ) : null}
              </article>
            ))}
          </div>
        </section>
      ) : null}
    </section>
  );
}
