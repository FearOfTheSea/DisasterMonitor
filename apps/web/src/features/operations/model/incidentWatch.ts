import type {
  ActiveIncident,
  DisasterType,
  IncidentCoverageState,
  IncidentSource,
} from '@/features/incidents/model/activeIncidents';

export type IncidentWatchCoverageState = IncidentCoverageState | 'stale';

export type IncidentWatchScope = {
  kind: 'country' | 'worldwide';
  country_code: string | null;
  country_name: string | null;
};

export type IncidentWatch = {
  watch_id: string;
  disaster: DisasterType;
  scope: IncidentWatchScope;
  enabled: boolean;
  refresh_interval_seconds: number;
  created_at: string;
  updated_at: string;
  next_refresh_at: string;
  last_checked_at: string | null;
  coverage_state: IncidentWatchCoverageState | null;
  unread_change_count: number;
};

export type IncidentWatchEvent = ActiveIncident & {
  physical_event_id: string;
  evidence_sources: IncidentSource[];
};

export type IncidentWatchChangeKind =
  | 'new_event'
  | 'observation_gap'
  | 'measurements_changed'
  | 'geometry_changed'
  | 'evidence_set_changed'
  | 'coverage_changed';

export type IncidentWatchChange = {
  change_id: string;
  watch_id: string;
  kind: IncidentWatchChangeKind;
  summary: string;
  detail: string;
  created_at: string;
  read_at: string | null;
  source_ids: string[];
  observation_id: string;
  previous_observation_id: string | null;
  before_hash: string | null;
  after_hash: string | null;
  incident: IncidentWatchEvent | null;
};

export type IncidentWatchCreate = {
  disaster: DisasterType;
  scope: { kind: 'worldwide' } | { kind: 'country'; country: string };
  refresh_interval_seconds: number;
};

export type IncidentWatchReadResult = {
  watch_id: string;
  marked_read_count: number;
  unread_change_count: number;
};
