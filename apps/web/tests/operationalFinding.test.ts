import { describe, expect, it } from 'vitest';

import type {
  ActiveIncident,
  ActiveIncidentsSnapshot,
  CompoundHazardCorrelation,
} from '@/features/incidents/model/activeIncidents';
import type {
  IncidentWatch,
  IncidentWatchChange,
  IncidentWatchEvent,
} from '@/features/operations/model/incidentWatch';
import { buildOperationalFindings } from '@/features/operations/model/operationalFinding';

const INCIDENT: ActiveIncident = {
  event_id: 'earthquake-1',
  disaster: 'earthquake',
  location: 'Fixture region',
  event_time: '2026-09-01T10:00:00Z',
  geometry: {
    kind: 'point',
    coordinates: [{ latitude: 10, longitude: 20 }],
    description: null,
    source_id: 'fixture-source',
    estimated: false,
  },
  measurements: [],
  provider_ids: ['fixture:earthquake-1'],
  provider_tier: 'primary',
  source_authority: 'scientific_authority',
  source: {
    source_id: 'fixture-source',
    publisher: 'Fixture Authority',
    title: 'Fixture record',
    canonical_url: 'https://example.test/fixture',
    published_at: '2026-09-01T10:00:00Z',
    updated_at: null,
    retrieved_at: '2026-09-01T10:10:00Z',
    snapshot_id: null,
  },
};

const WATCH: IncidentWatch = {
  watch_id: 'watch-1',
  disaster: 'flood',
  scope: { kind: 'country', country_code: 'VNM', country_name: 'Vietnam' },
  enabled: true,
  refresh_interval_seconds: 900,
  created_at: '2026-09-01T08:00:00Z',
  updated_at: '2026-09-01T10:10:00Z',
  next_refresh_at: '2026-09-01T10:15:00Z',
  last_checked_at: '2026-09-01T10:00:00Z',
  coverage_state: 'stale',
  unread_change_count: 1,
};

const WATCH_INCIDENT: IncidentWatchEvent = {
  ...INCIDENT,
  physical_event_id: 'physical:earthquake-1',
  evidence_sources: [],
};

const CHANGE: IncidentWatchChange = {
  change_id: 'change-1',
  watch_id: WATCH.watch_id,
  kind: 'new_event',
  summary: 'Exact watch summary',
  detail: 'Exact watch detail',
  created_at: '2026-09-01T10:00:00Z',
  read_at: null,
  source_ids: ['fixture-source'],
  observation_id: 'observation-1',
  previous_observation_id: null,
  before_hash: null,
  after_hash: 'sha256:fixture',
  incident: WATCH_INCIDENT,
};

const CORRELATION: CompoundHazardCorrelation = {
  correlation_id: 'correlation-1',
  rule_id: 'compound-hazard:earthquake-landslide:v1',
  relationship: 'spatiotemporal_association',
  first_event_id: INCIDENT.event_id,
  first_physical_event_id: null,
  first_disaster: 'earthquake',
  second_event_id: 'landslide-1',
  second_physical_event_id: null,
  second_disaster: 'landslide',
  distance_km: 12,
  time_delta_seconds: 600,
  source_ids: ['fixture-source', 'landslide-source'],
  summary: 'Exact descriptive correlation summary.',
  limitation: 'Spatial and temporal proximity does not establish causation.',
};

const SNAPSHOT: ActiveIncidentsSnapshot = {
  retrieved_at: '2026-09-01T10:10:00Z',
  incidents: [INCIDENT],
  coverage: [
    {
      disaster: 'earthquake',
      state: 'degraded',
      incident_count: 1,
      providers: ['USGS'],
      detail: 'Exact active coverage detail.',
    },
    {
      disaster: 'flood',
      state: 'no_matching_records',
      incident_count: 0,
      providers: ['CEMS'],
      detail: 'Successful empty.',
    },
  ],
  warnings: ['Exact active warning.'],
  correlations: [CORRELATION],
};

describe('buildOperationalFindings', () => {
  it('deterministically aggregates only existing typed facts and preserves provenance', () => {
    const findings = buildOperationalFindings({
      watches: [WATCH],
      watchChanges: [CHANGE, { ...CHANGE, change_id: 'read', read_at: '2026-09-01' }],
      activeSnapshot: SNAPSHOT,
      displayedIncidents: SNAPSHOT.incidents,
      displayedCorrelations: SNAPSHOT.correlations,
    });

    expect(findings.map((finding) => finding.kind)).toEqual([
      'watch_change',
      'watch_coverage',
      'active_coverage',
      'active_warning',
      'compound_correlation',
    ]);
    expect(findings[0]).toMatchObject({
      title: CHANGE.summary,
      detail: CHANGE.detail,
      sourceIds: CHANGE.source_ids,
      watchId: WATCH.watch_id,
      changeId: CHANGE.change_id,
      focusIncident: WATCH_INCIDENT,
    });
    expect(findings.find((item) => item.kind === 'active_coverage')).toMatchObject({
      detail: 'Exact active coverage detail.',
      sourceIds: ['USGS'],
    });
    expect(findings.some((item) => item.detail === 'Successful empty.')).toBe(false);
    expect(findings.find((item) => item.kind === 'compound_correlation')).toMatchObject(
      {
        title: CORRELATION.summary,
        detail: CORRELATION.limitation,
        sourceIds: CORRELATION.source_ids,
        focusIncident: INCIDENT,
      },
    );
  });
});
