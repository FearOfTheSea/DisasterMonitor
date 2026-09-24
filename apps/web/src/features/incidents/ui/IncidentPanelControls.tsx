'use client';

import type { ActiveIncidentsStatus } from '@/features/incidents/hooks/useActiveIncidents';
import type {
  ActiveIncidentsSnapshot,
  DisasterType,
  IncidentView,
} from '@/features/incidents/model/activeIncidents';
import { HAZARD_OPTIONS } from '@/features/incidents/ui/incidentPresentation';

type IncidentPanelControlsProps = {
  snapshot?: ActiveIncidentsSnapshot;
  status: ActiveIncidentsStatus;
  error?: string;
  search: string;
  onSearchChange: (value: string) => void;
  view: IncidentView;
  onViewChange?: (value: IncidentView) => void;
  hazard?: DisasterType;
  onHazardChange?: (value: DisasterType | undefined) => void;
  occurrenceStart: string;
  occurrenceEnd: string;
  onOccurrenceStartChange?: (value: string) => void;
  onOccurrenceEndChange?: (value: string) => void;
  onRefresh: () => void | Promise<void>;
};

const VIEW_LABELS: Record<IncidentView, string> = {
  recent: 'Recent onset',
  ongoing: 'Ongoing',
  recently_updated: 'Recently updated',
  historical: 'Historical window',
};

function formatSnapshotTime(snapshot?: ActiveIncidentsSnapshot): string {
  if (!snapshot) return 'No snapshot available';
  const timestamp = new Date(snapshot.retrieved_at);
  if (Number.isNaN(timestamp.getTime())) return snapshot.retrieved_at;
  return timestamp.toLocaleString(undefined, {
    month: 'short',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
  });
}

function StatusIcon({ status }: { status: ActiveIncidentsStatus }) {
  if (status === 'loading') {
    return <span className="incident-status-spinner" aria-hidden="true" />;
  }
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <circle cx="12" cy="12" r="9" />
      {status === 'success' ? (
        <path d="m8 12 2.5 2.5L16 9" />
      ) : (
        <>
          <path d="M12 10v6" />
          <path d="M12 7h.01" />
        </>
      )}
    </svg>
  );
}

export function IncidentPanelControls({
  snapshot,
  status,
  error,
  search,
  onSearchChange,
  view,
  onViewChange,
  hazard,
  onHazardChange,
  occurrenceStart,
  occurrenceEnd,
  onOccurrenceStartChange,
  onOccurrenceEndChange,
  onRefresh,
}: IncidentPanelControlsProps) {
  const offline = status === 'offline';
  const unavailable = status === 'error';
  const loading = status === 'loading';
  const hasFilters = Boolean(
    search.trim() || view !== 'recent' || hazard || occurrenceStart || occurrenceEnd,
  );
  const statusTitle = offline
    ? 'Offline snapshot'
    : unavailable
      ? 'Incidents unavailable'
      : loading
        ? snapshot
          ? 'Updating snapshot'
          : 'Loading active incidents…'
        : 'Live snapshot';
  const statusDetail = unavailable
    ? (error ?? 'Incident providers could not be reached.')
    : loading && !snapshot
      ? 'Checking trusted source networks…'
      : `${snapshot && !loading ? 'Last updated' : 'Keeping data from'} ${formatSnapshotTime(snapshot)}`;
  const statusRole = unavailable ? 'alert' : 'status';

  function clearFilters() {
    onSearchChange('');
    onViewChange?.('recent');
    onHazardChange?.(undefined);
    onOccurrenceStartChange?.('');
    onOccurrenceEndChange?.('');
  }

  return (
    <>
      <div
        className={`incident-data-status incident-data-status-${status}`}
        role={statusRole}
        aria-label="Incident data status"
        aria-live="polite"
      >
        <StatusIcon status={status} />
        <span>
          <strong>{statusTitle}</strong>
          <small>{statusDetail}</small>
          {loading && !snapshot ? (
            <small>Some providers can take a moment to respond.</small>
          ) : null}
        </span>
        <button type="button" onClick={() => void onRefresh()} disabled={loading}>
          {loading ? 'Updating…' : offline || unavailable ? 'Try again' : 'Refresh'}
        </button>
      </div>
      <div className="incident-search">
        <svg
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.7"
          aria-hidden="true"
        >
          <circle cx="10.5" cy="10.5" r="6.5" />
          <path d="m16 16 4.5 4.5" />
        </svg>
        <input
          type="search"
          aria-label="Search loaded events by location or source"
          placeholder="Search loaded events"
          value={search}
          onChange={(event) => onSearchChange(event.target.value)}
        />
      </div>
      <div className="incident-query-controls" aria-label="Incident filters">
        <label>
          <span>View</span>
          <select
            aria-label="Incident view"
            value={view}
            onChange={(event) => onViewChange?.(event.target.value as IncidentView)}
          >
            {Object.entries(VIEW_LABELS).map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
        </label>
        <label>
          <span>Hazard</span>
          <select
            aria-label="Hazard filter"
            value={hazard ?? ''}
            onChange={(event) =>
              onHazardChange?.(
                event.target.value ? (event.target.value as DisasterType) : undefined,
              )
            }
          >
            <option value="">All hazards</option>
            {HAZARD_OPTIONS.map((item) => (
              <option key={item.value} value={item.value}>
                {item.label}
              </option>
            ))}
          </select>
        </label>
        <button
          type="button"
          className="incident-clear-filters"
          onClick={clearFilters}
          disabled={!hasFilters}
        >
          Clear filters
        </button>
        {view === 'historical' ? (
          <div className="incident-date-controls">
            <label>
              <span>Occurrence start (UTC)</span>
              <input
                type="datetime-local"
                aria-label="Historical occurrence start UTC"
                value={occurrenceStart}
                max={occurrenceEnd || undefined}
                onChange={(event) => onOccurrenceStartChange?.(event.target.value)}
              />
            </label>
            <label>
              <span>Occurrence end (UTC)</span>
              <input
                type="datetime-local"
                aria-label="Historical occurrence end UTC"
                value={occurrenceEnd}
                min={occurrenceStart || undefined}
                onChange={(event) => onOccurrenceEndChange?.(event.target.value)}
              />
            </label>
            <small>End time must follow the start time.</small>
          </div>
        ) : null}
      </div>
    </>
  );
}
