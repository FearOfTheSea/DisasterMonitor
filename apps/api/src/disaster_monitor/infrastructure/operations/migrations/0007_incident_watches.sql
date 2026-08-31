CREATE TABLE IF NOT EXISTS incident_watch (
    watch_id text PRIMARY KEY,
    disaster text NOT NULL CHECK (
        disaster IN (
            'earthquake', 'flood', 'wildfire', 'landslide',
            'tropical_cyclone', 'volcanic_eruption'
        )
    ),
    scope_kind text NOT NULL CHECK (scope_kind IN ('country', 'worldwide')),
    country_code text,
    country_name text,
    enabled boolean NOT NULL DEFAULT true,
    refresh_interval_seconds integer NOT NULL CHECK (
        refresh_interval_seconds BETWEEN 300 AND 86400
    ),
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL,
    next_refresh_at timestamptz NOT NULL,
    last_checked_at timestamptz,
    coverage_state text CHECK (
        coverage_state IS NULL OR coverage_state IN (
            'events_found', 'no_matching_records', 'stale',
            'degraded', 'unavailable'
        )
    ),
    latest_observation_id text,
    latest_successful_observation_id text,
    CHECK (
        (scope_kind = 'worldwide' AND country_code IS NULL AND country_name IS NULL)
        OR
        (scope_kind = 'country' AND country_code ~ '^[A-Z]{3}$'
         AND country_name IS NOT NULL AND char_length(country_name) > 0)
    )
);

CREATE INDEX IF NOT EXISTS incident_watch_due_idx
    ON incident_watch(next_refresh_at, watch_id)
    WHERE enabled = true;

CREATE TABLE IF NOT EXISTS incident_watch_observation (
    observation_id text PRIMARY KEY,
    watch_id text NOT NULL REFERENCES incident_watch(watch_id) ON DELETE CASCADE,
    observed_at timestamptz NOT NULL,
    coverage_state text NOT NULL CHECK (
        coverage_state IN (
            'events_found', 'no_matching_records', 'stale',
            'degraded', 'unavailable'
        )
    ),
    incidents jsonb NOT NULL CHECK (jsonb_typeof(incidents) = 'array'),
    provider_names jsonb NOT NULL CHECK (jsonb_typeof(provider_names) = 'array'),
    provider_source_ids jsonb NOT NULL CHECK (
        jsonb_typeof(provider_source_ids) = 'array'
    ),
    warnings jsonb NOT NULL CHECK (jsonb_typeof(warnings) = 'array'),
    state_hash text NOT NULL CHECK (state_hash ~ '^sha256:[0-9a-f]{64}$'),
    successful boolean NOT NULL,
    retryable boolean NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (watch_id, state_hash)
);

CREATE INDEX IF NOT EXISTS incident_watch_observation_watch_time_idx
    ON incident_watch_observation(watch_id, observed_at DESC, observation_id DESC);

ALTER TABLE incident_watch
    ADD CONSTRAINT incident_watch_latest_observation_fk
    FOREIGN KEY (latest_observation_id)
    REFERENCES incident_watch_observation(observation_id)
    ON DELETE SET NULL;

ALTER TABLE incident_watch
    ADD CONSTRAINT incident_watch_latest_successful_observation_fk
    FOREIGN KEY (latest_successful_observation_id)
    REFERENCES incident_watch_observation(observation_id)
    ON DELETE SET NULL;

CREATE TABLE IF NOT EXISTS incident_watch_change (
    change_id text PRIMARY KEY,
    watch_id text NOT NULL REFERENCES incident_watch(watch_id) ON DELETE CASCADE,
    kind text NOT NULL CHECK (
        kind IN (
            'new_event', 'observation_gap', 'measurements_changed',
            'geometry_changed', 'evidence_set_changed', 'coverage_changed'
        )
    ),
    summary text NOT NULL CHECK (char_length(summary) BETWEEN 1 AND 500),
    detail text NOT NULL CHECK (char_length(detail) BETWEEN 1 AND 2000),
    occurred_at timestamptz NOT NULL,
    source_ids jsonb NOT NULL CHECK (jsonb_typeof(source_ids) = 'array'),
    observation_id text NOT NULL REFERENCES incident_watch_observation(observation_id)
        ON DELETE CASCADE,
    previous_observation_id text REFERENCES incident_watch_observation(observation_id)
        ON DELETE SET NULL,
    before_hash text CHECK (
        before_hash IS NULL OR before_hash ~ '^sha256:[0-9a-f]{64}$'
    ),
    after_hash text CHECK (
        after_hash IS NULL OR after_hash ~ '^sha256:[0-9a-f]{64}$'
    ),
    incident jsonb CHECK (incident IS NULL OR jsonb_typeof(incident) = 'object'),
    read_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS incident_watch_change_watch_time_idx
    ON incident_watch_change(watch_id, occurred_at DESC, change_id DESC);

CREATE INDEX IF NOT EXISTS incident_watch_change_observation_idx
    ON incident_watch_change(observation_id);

CREATE INDEX IF NOT EXISTS incident_watch_change_previous_observation_idx
    ON incident_watch_change(previous_observation_id)
    WHERE previous_observation_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS incident_watch_change_unread_idx
    ON incident_watch_change(watch_id, change_id)
    WHERE read_at IS NULL;
