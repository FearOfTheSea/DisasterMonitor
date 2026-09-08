CREATE TABLE IF NOT EXISTS provider_attempt (
    attempt_id bigserial PRIMARY KEY,
    source_id text NOT NULL,
    attempted_at timestamptz NOT NULL,
    outcome text NOT NULL CHECK (outcome IN ('success', 'empty', 'failed', 'incomplete')),
    reason_code text,
    retryable boolean NOT NULL DEFAULT false,
    http_status integer,
    records_seen integer NOT NULL CHECK (records_seen >= 0)
);

CREATE INDEX IF NOT EXISTS provider_attempt_source_time_idx
    ON provider_attempt(source_id, attempted_at DESC, attempt_id DESC);
