CREATE TABLE IF NOT EXISTS imagery_requests (
    request_id text PRIMARY KEY,
    incident_id text NOT NULL,
    owner_scope text NOT NULL,
    request_version integer NOT NULL CHECK (request_version > 0),
    reference_time timestamptz NOT NULL,
    state text NOT NULL,
    payload jsonb NOT NULL CHECK (jsonb_typeof(payload) = 'object'),
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL
);

CREATE INDEX IF NOT EXISTS imagery_requests_incident_idx
    ON imagery_requests(owner_scope, incident_id, updated_at DESC, request_id);

CREATE TABLE IF NOT EXISTS imagery_regions (
    request_id text NOT NULL REFERENCES imagery_requests(request_id) ON DELETE CASCADE,
    region_version integer NOT NULL CHECK (region_version > 0),
    region_id text NOT NULL,
    geometry_hash text NOT NULL CHECK (geometry_hash ~ '^[0-9a-f]{64}$'),
    association text NOT NULL,
    core_geometry geometry(MultiPolygon, 4326) NOT NULL,
    inspection_geometry geometry(MultiPolygon, 4326) NOT NULL,
    payload jsonb NOT NULL CHECK (jsonb_typeof(payload) = 'object'),
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (request_id, region_version),
    UNIQUE (request_id, region_id, region_version)
);

CREATE INDEX IF NOT EXISTS imagery_regions_core_gist_idx
    ON imagery_regions USING gist (core_geometry);

CREATE TABLE IF NOT EXISTS imagery_time_plans (
    request_id text NOT NULL REFERENCES imagery_requests(request_id) ON DELETE CASCADE,
    request_version integer NOT NULL CHECK (request_version > 0),
    policy_version text NOT NULL,
    payload jsonb NOT NULL CHECK (jsonb_typeof(payload) = 'object'),
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (request_id, request_version)
);

CREATE TABLE IF NOT EXISTS imagery_observations (
    request_id text NOT NULL REFERENCES imagery_requests(request_id) ON DELETE CASCADE,
    request_version integer NOT NULL CHECK (request_version > 0),
    observation_id text NOT NULL,
    sensor text NOT NULL CHECK (sensor IN ('sentinel-1', 'sentinel-2')),
    provider text NOT NULL,
    product_id text NOT NULL,
    revision text,
    capture_start timestamptz NOT NULL,
    capture_end timestamptz NOT NULL,
    footprint geometry(MultiPolygon, 4326) NOT NULL,
    payload jsonb NOT NULL CHECK (jsonb_typeof(payload) = 'object'),
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (request_id, request_version, observation_id)
);

CREATE INDEX IF NOT EXISTS imagery_observations_capture_idx
    ON imagery_observations(request_id, sensor, capture_start DESC, observation_id);

CREATE TABLE IF NOT EXISTS imagery_selections (
    selection_id text PRIMARY KEY,
    request_id text NOT NULL REFERENCES imagery_requests(request_id) ON DELETE CASCADE,
    request_version integer NOT NULL CHECK (request_version > 0),
    sensor text NOT NULL CHECK (sensor IN ('sentinel-1', 'sentinel-2')),
    temporal_role text NOT NULL,
    observation_id text,
    pinned boolean NOT NULL DEFAULT false,
    payload jsonb NOT NULL CHECK (jsonb_typeof(payload) = 'object'),
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS imagery_artifacts (
    artifact_id text PRIMARY KEY,
    request_id text NOT NULL REFERENCES imagery_requests(request_id) ON DELETE CASCADE,
    selection_id text,
    storage_key text NOT NULL,
    content_type text NOT NULL,
    sha256 text NOT NULL CHECK (sha256 ~ '^[0-9a-f]{64}$'),
    byte_count bigint NOT NULL CHECK (byte_count > 0),
    grid jsonb NOT NULL CHECK (jsonb_typeof(grid) = 'object'),
    manifest jsonb NOT NULL CHECK (jsonb_typeof(manifest) = 'object'),
    pinned boolean NOT NULL DEFAULT false,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS imagery_jobs (
    job_id text PRIMARY KEY,
    request_id text NOT NULL REFERENCES imagery_requests(request_id) ON DELETE CASCADE,
    request_version integer NOT NULL CHECK (request_version > 0),
    stage text NOT NULL,
    status text NOT NULL CHECK (status IN (
        'queued', 'running', 'retry_wait', 'succeeded', 'failed', 'cancelled'
    )),
    attempt integer NOT NULL DEFAULT 0 CHECK (attempt >= 0),
    claimed_by text,
    claimed_at timestamptz,
    lease_expires_at timestamptz,
    fencing_token bigint NOT NULL DEFAULT 0 CHECK (fencing_token >= 0),
    next_attempt_at timestamptz NOT NULL,
    progress jsonb NOT NULL DEFAULT '{}'::jsonb,
    error_code text,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS imagery_jobs_due_idx
    ON imagery_jobs(status, next_attempt_at, job_id);

CREATE TABLE IF NOT EXISTS imagery_watches (
    watch_id text PRIMARY KEY,
    request_id text NOT NULL UNIQUE REFERENCES imagery_requests(request_id) ON DELETE CASCADE,
    enabled boolean NOT NULL DEFAULT false,
    interval_seconds integer NOT NULL CHECK (interval_seconds BETWEEN 3600 AND 86400),
    next_check_at timestamptz,
    last_checked_at timestamptz,
    last_success_at timestamptz,
    end_policy text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS imagery_watches_due_idx
    ON imagery_watches(next_check_at, watch_id)
    WHERE enabled = true;

CREATE TABLE IF NOT EXISTS imagery_quota_reservations (
    reservation_id text PRIMARY KEY,
    request_id text NOT NULL REFERENCES imagery_requests(request_id) ON DELETE CASCADE,
    account_key text NOT NULL,
    budget_window text NOT NULL,
    estimated_processing_units numeric NOT NULL CHECK (estimated_processing_units >= 0),
    actual_processing_units numeric CHECK (actual_processing_units IS NULL OR actual_processing_units >= 0),
    status text NOT NULL CHECK (status IN ('reserved', 'settled', 'released', 'deferred')),
    owner_id text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    settled_at timestamptz
);

CREATE INDEX IF NOT EXISTS imagery_quota_window_idx
    ON imagery_quota_reservations(account_key, budget_window, status);
