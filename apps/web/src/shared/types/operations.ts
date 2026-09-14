export type FreshnessState = 'fresh' | 'stale' | 'unavailable' | 'never_ingested';

export type ProviderFreshness = {
  source_id: string;
  state: FreshnessState;
  last_attempt_at: string | null;
  last_success_at: string | null;
  effective_at: string | null;
  age_seconds: number | null;
  expected_freshness_seconds: number;
  consecutive_failures: number;
  latest_error_code: string | null;
  health_state?: 'healthy' | 'stale' | 'degraded' | 'unavailable' | 'misconfigured';
  source_publication_age_seconds?: number | null;
  retrieval_lag_seconds?: number | null;
  parse_failures?: number;
  admission_failures?: number;
  truncated?: boolean;
  stale_projection_age_seconds?: number | null;
  hazard?: string | null;
};

export type ProviderBudget = {
  provider_id: string;
  budget_window: string;
  limit_units: number;
  reserved_units: number;
  settled_units: number;
  released_units: number;
  remaining_units: number;
  reset_at: string;
};

export type CountryCatalogUpdateState =
  'never_run' | 'running' | 'updated' | 'unchanged' | 'failed';

export type CountryCatalogSource = {
  source_id: string;
  version: string;
  revision: string;
  sha256: string;
};

export type CountryCatalogStatus = {
  state: CountryCatalogUpdateState;
  active_version: string;
  country_count: number;
  automatic_updates_enabled: boolean;
  trigger: 'manual' | 'scheduled' | 'script' | null;
  last_attempt_at: string | null;
  last_success_at: string | null;
  next_scheduled_at: string | null;
  message: string;
  failure_code: string | null;
  sources: CountryCatalogSource[];
};

export type EvidenceSnapshot = {
  snapshot_id: string;
  source_id: string;
  provider_revision: string;
  retrieved_at: string;
  published_at: string | null;
  observed_at: string | null;
  effective_at: string;
  content_type: string;
  payload_sha256: string;
  payload_size_bytes: number;
  rights_id: string;
  content_available: boolean;
  content_deleted_at: string | null;
  content_deletion_reason: string | null;
};

export type OperatorReviewResult = {
  action_id: string;
  operator_id: string;
  state_version: string;
  decision: 'reviewed';
  reviewed_at: string;
  created: boolean;
};
