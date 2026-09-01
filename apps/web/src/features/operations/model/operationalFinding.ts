import type {
  ActiveIncident,
  ActiveIncidentsSnapshot,
  CompoundHazardCorrelation,
  DisasterType,
} from '@/features/incidents/model/activeIncidents';
import type {
  IncidentWatch,
  IncidentWatchChange,
} from '@/features/operations/model/incidentWatch';

export type OperationalFindingKind =
  | 'watch_change'
  | 'watch_coverage'
  | 'active_coverage'
  | 'active_warning'
  | 'compound_correlation';

export type OperationalFinding = {
  id: string;
  kind: OperationalFindingKind;
  title: string;
  detail: string;
  sourceIds: string[];
  occurredAt?: string;
  watchId?: string;
  changeId?: string;
  focusIncident?: ActiveIncident;
};

type OperationalFindingInput = {
  watches: readonly IncidentWatch[];
  watchChanges: readonly IncidentWatchChange[];
  activeSnapshot?: ActiveIncidentsSnapshot;
  displayedIncidents?: readonly ActiveIncident[];
  displayedCorrelations?: readonly CompoundHazardCorrelation[];
};

const DISASTER_LABELS: Record<DisasterType, string> = {
  earthquake: 'Earthquake',
  flood: 'Flood',
  wildfire: 'Wildfire',
  landslide: 'Landslide',
  tropical_cyclone: 'Tropical cyclone',
  volcanic_eruption: 'Volcanic eruption',
};

const WATCH_COVERAGE_LABELS = {
  degraded: 'Degraded',
  unavailable: 'Unavailable',
  stale: 'Stale evidence',
} as const;

function mappableIncident(incident: ActiveIncident | null | undefined) {
  const geometry = incident?.geometry;
  if (!incident || !geometry || geometry.kind === 'descriptive') return undefined;
  if (geometry.kind === 'point' && geometry.coordinates.length !== 1) return undefined;
  if (geometry.kind === 'track' && geometry.coordinates.length < 2) return undefined;
  if (geometry.kind === 'area' && geometry.coordinates.length < 3) return undefined;
  return incident;
}

function watchScopeLabel(watch: IncidentWatch): string {
  return watch.scope.country_name ?? 'Worldwide';
}

export function buildOperationalFindings({
  watches,
  watchChanges,
  activeSnapshot,
  displayedIncidents = activeSnapshot?.incidents ?? [],
  displayedCorrelations = activeSnapshot?.correlations ?? [],
}: OperationalFindingInput): OperationalFinding[] {
  const findings: OperationalFinding[] = [];
  const incidentsById = new Map(
    displayedIncidents.map((incident) => [incident.event_id, incident]),
  );

  const unreadChanges = watchChanges
    .filter((change) => change.read_at === null)
    .toSorted(
      (first, second) =>
        second.created_at.localeCompare(first.created_at) ||
        first.change_id.localeCompare(second.change_id),
    );
  for (const change of unreadChanges) {
    findings.push({
      id: `watch-change:${change.change_id}`,
      kind: 'watch_change',
      title: change.summary,
      detail: change.detail,
      sourceIds: [...change.source_ids],
      occurredAt: change.created_at,
      watchId: change.watch_id,
      changeId: change.change_id,
      focusIncident: mappableIncident(change.incident),
    });
  }

  const coverageWatches = watches
    .filter(
      (watch) =>
        watch.coverage_state === 'degraded' ||
        watch.coverage_state === 'unavailable' ||
        watch.coverage_state === 'stale',
    )
    .toSorted((first, second) => first.watch_id.localeCompare(second.watch_id));
  for (const watch of coverageWatches) {
    const state = watch.coverage_state as keyof typeof WATCH_COVERAGE_LABELS;
    findings.push({
      id: `watch-coverage:${watch.watch_id}:${state}`,
      kind: 'watch_coverage',
      title: `${watchScopeLabel(watch)} ${DISASTER_LABELS[watch.disaster].toLowerCase()} watch · ${WATCH_COVERAGE_LABELS[state]}`,
      detail: `Latest watch coverage state: ${WATCH_COVERAGE_LABELS[state]}.`,
      sourceIds: [],
      occurredAt: watch.last_checked_at ?? watch.updated_at,
      watchId: watch.watch_id,
    });
  }

  if (activeSnapshot) {
    for (const coverage of activeSnapshot.coverage) {
      if (coverage.state !== 'degraded' && coverage.state !== 'unavailable') continue;
      findings.push({
        id: `active-coverage:${coverage.disaster}:${coverage.state}`,
        kind: 'active_coverage',
        title: `${DISASTER_LABELS[coverage.disaster]} coverage · ${coverage.state === 'degraded' ? 'Degraded' : 'Unavailable'}`,
        detail: coverage.detail,
        sourceIds: [...coverage.providers],
        occurredAt: activeSnapshot.retrieved_at,
      });
    }
    activeSnapshot.warnings.forEach((warning, index) => {
      findings.push({
        id: `active-warning:${index}:${warning}`,
        kind: 'active_warning',
        title: 'Active Incidents retrieval warning',
        detail: warning,
        sourceIds: [],
        occurredAt: activeSnapshot.retrieved_at,
      });
    });
  }

  for (const correlation of [...displayedCorrelations].toSorted((first, second) =>
    first.correlation_id.localeCompare(second.correlation_id),
  )) {
    const firstIncident = incidentsById.get(correlation.first_event_id);
    const secondIncident = incidentsById.get(correlation.second_event_id);
    findings.push({
      id: `compound-correlation:${correlation.correlation_id}`,
      kind: 'compound_correlation',
      title: correlation.summary,
      detail: correlation.limitation,
      sourceIds: [...correlation.source_ids],
      focusIncident:
        mappableIncident(firstIncident) ?? mappableIncident(secondIncident),
    });
  }

  return findings;
}
