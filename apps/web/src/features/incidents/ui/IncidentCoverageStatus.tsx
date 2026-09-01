import type {
  ActiveIncident,
  ActiveIncidentsSnapshot,
  DisasterIncidentCoverage,
  DisasterType,
  IncidentCoverageState,
} from '@/features/incidents/model/activeIncidents';

const DISASTERS: { value: DisasterType; label: string }[] = [
  { value: 'earthquake', label: 'Earthquake' },
  { value: 'flood', label: 'Flood' },
  { value: 'wildfire', label: 'Wildfire' },
  { value: 'landslide', label: 'Landslide' },
  { value: 'tropical_cyclone', label: 'Tropical cyclone' },
  { value: 'volcanic_eruption', label: 'Volcanic eruption' },
];

const COVERAGE_LABELS: Record<IncidentCoverageState, string> = {
  events_found: 'Events found',
  no_matching_records: 'No matching records',
  degraded: 'Degraded',
  unavailable: 'Unavailable',
};

function formatTime(value: string): string {
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleString();
}

function coverageFor(
  snapshot: ActiveIncidentsSnapshot,
  disaster: DisasterType,
): DisasterIncidentCoverage {
  return (
    snapshot.coverage.find((item) => item.disaster === disaster) ?? {
      disaster,
      state: 'unavailable',
      incident_count: 0,
      providers: [],
      detail: 'The API returned no coverage result for this disaster.',
    }
  );
}

function sourceTimestamp(incident: ActiveIncident): { label: string; value: string } {
  if (incident.source.updated_at) {
    return { label: 'Source updated', value: incident.source.updated_at };
  }
  if (incident.source.published_at) {
    return { label: 'Source published', value: incident.source.published_at };
  }
  return { label: 'Source retrieved', value: incident.source.retrieved_at };
}

function CoverageStatusIcon({ state }: { state: IncidentCoverageState }) {
  if (state === 'events_found') {
    return (
      <svg viewBox="0 0 16 16" aria-hidden="true">
        <circle cx="8" cy="8" r="7" />
        <path d="m4.5 8.1 2.1 2.1 4.9-4.9" />
      </svg>
    );
  }
  if (state === 'no_matching_records') {
    return (
      <svg viewBox="0 0 16 16" aria-hidden="true">
        <circle cx="8" cy="8" r="7" />
        <path d="M4.5 8h7" />
      </svg>
    );
  }
  return (
    <svg viewBox="0 0 16 16" aria-hidden="true">
      <path d="M8 1.5 15 14H1Z" />
      <path d="M8 5v4.5M8 12h.01" />
    </svg>
  );
}

export function IncidentCoverageStatus({
  snapshot,
}: {
  snapshot: ActiveIncidentsSnapshot;
}) {
  const partial = snapshot.coverage.some(
    (item) => item.state === 'degraded' || item.state === 'unavailable',
  );

  return (
    <section className="incident-coverage-status" aria-labelledby="coverage-heading">
      <div className="incident-section-heading">
        <div>
          <h3 id="coverage-heading">Provider coverage</h3>
          <p className="incident-retrieval-time">
            Snapshot retrieved:{' '}
            <time dateTime={snapshot.retrieved_at}>
              {formatTime(snapshot.retrieved_at)}
            </time>
          </p>
        </div>
        {partial ? <span className="incident-partial">Coverage is partial</span> : null}
      </div>
      <div className="incident-coverage-grid">
        {DISASTERS.map((definition) => {
          const coverage = coverageFor(snapshot, definition.value);
          const sourceRecords = snapshot.incidents.filter(
            (incident) => incident.disaster === definition.value,
          );
          const timestamps = new Map<string, { label: string; value: string }>();
          for (const incident of sourceRecords) {
            const timestamp = sourceTimestamp(incident);
            timestamps.set(incident.source.source_id, timestamp);
          }
          return (
            <article
              key={definition.value}
              className={`coverage-item coverage-item-${coverage.state}`}
              data-testid="incident-coverage"
            >
              <div>
                <strong>{definition.label}</strong>
                <span className={`coverage-state coverage-${coverage.state}`}>
                  <CoverageStatusIcon state={coverage.state} />
                  {COVERAGE_LABELS[coverage.state]}
                </span>
              </div>
              <small>{coverage.detail}</small>
              <small>
                Providers:{' '}
                {coverage.providers.length > 0
                  ? coverage.providers.join(', ')
                  : 'No providers reported'}
              </small>
              {[...timestamps].map(([sourceId, timestamp]) => (
                <small key={sourceId}>
                  {sourceId} · {timestamp.label}: {formatTime(timestamp.value)}
                </small>
              ))}
            </article>
          );
        })}
      </div>
      {snapshot.warnings.length > 0 ? (
        <section
          className="incident-warnings"
          aria-labelledby="incident-warnings-heading"
        >
          <h3 id="incident-warnings-heading">Retrieval warnings</h3>
          <p>
            Provider notices describe coverage limits; they are not disaster claims.
          </p>
          <ul>
            {snapshot.warnings.map((warning) => (
              <li key={warning}>{warning}</li>
            ))}
          </ul>
        </section>
      ) : null}
    </section>
  );
}
