CREATE EXTENSION IF NOT EXISTS postgis;

CREATE TABLE IF NOT EXISTS source (
    source_id text PRIMARY KEY,
    rights_id text,
    expected_freshness_seconds integer,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS source_snapshot (
    snapshot_id text PRIMARY KEY,
    idempotency_key text NOT NULL UNIQUE,
    source_id text NOT NULL REFERENCES source(source_id),
    canonical_request_identity text NOT NULL,
    provider_revision text NOT NULL,
    retrieved_at timestamptz NOT NULL,
    published_at timestamptz,
    observed_at timestamptz,
    response_status integer NOT NULL CHECK (response_status BETWEEN 200 AND 299),
    content_type text NOT NULL,
    payload_sha256 text NOT NULL CHECK (payload_sha256 ~ '^sha256:[0-9a-f]{64}$'),
    payload_size_bytes bigint NOT NULL CHECK (payload_size_bytes > 0),
    blob_uri text NOT NULL,
    rights_id text NOT NULL,
    content_deleted_at timestamptz,
    content_deletion_reason text,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS source_snapshot_source_time_idx
    ON source_snapshot(source_id, retrieved_at DESC);

CREATE OR REPLACE FUNCTION protect_source_snapshot() RETURNS trigger AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'source_snapshot rows are append-only';
    END IF;
    IF ROW(NEW.snapshot_id, NEW.idempotency_key, NEW.source_id,
           NEW.canonical_request_identity, NEW.provider_revision, NEW.retrieved_at,
           NEW.published_at, NEW.observed_at, NEW.response_status, NEW.content_type,
           NEW.payload_sha256, NEW.payload_size_bytes, NEW.rights_id)
       IS DISTINCT FROM
       ROW(OLD.snapshot_id, OLD.idempotency_key, OLD.source_id,
           OLD.canonical_request_identity, OLD.provider_revision, OLD.retrieved_at,
           OLD.published_at, OLD.observed_at, OLD.response_status, OLD.content_type,
           OLD.payload_sha256, OLD.payload_size_bytes, OLD.rights_id) THEN
        RAISE EXCEPTION 'immutable source_snapshot fields cannot change';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS source_snapshot_append_only ON source_snapshot;
CREATE TRIGGER source_snapshot_append_only
BEFORE UPDATE OR DELETE ON source_snapshot
FOR EACH ROW EXECUTE FUNCTION protect_source_snapshot();

CREATE TABLE IF NOT EXISTS ingest_job (
    job_id text PRIMARY KEY,
    source_id text NOT NULL REFERENCES source(source_id),
    canonical_request_identity text NOT NULL,
    scheduled_for timestamptz NOT NULL,
    status text NOT NULL CHECK (status IN ('queued','running','retry','succeeded','dead_letter')),
    attempt_count integer NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
    max_attempts integer NOT NULL CHECK (max_attempts > 0),
    claimed_by text,
    claimed_at timestamptz,
    completed_at timestamptz,
    last_failed_at timestamptz,
    last_error_code text,
    created_at timestamptz NOT NULL
);

CREATE INDEX IF NOT EXISTS ingest_job_claim_idx
    ON ingest_job(status, scheduled_for, job_id);

CREATE TABLE IF NOT EXISTS normalized_observation (
    observation_id text PRIMARY KEY,
    snapshot_id text NOT NULL REFERENCES source_snapshot(snapshot_id),
    source_id text NOT NULL REFERENCES source(source_id),
    observation_type text NOT NULL,
    effective_at timestamptz NOT NULL,
    parser_version text NOT NULL,
    canonical_document jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS physical_event (
    physical_event_id text PRIMARY KEY,
    hazard text NOT NULL,
    country_code char(3) NOT NULL,
    representative_geometry geometry(Geometry, 4326),
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS event_observation_link (
    physical_event_id text NOT NULL REFERENCES physical_event(physical_event_id),
    observation_id text NOT NULL REFERENCES normalized_observation(observation_id),
    assignment_status text NOT NULL,
    rationale text NOT NULL,
    PRIMARY KEY (physical_event_id, observation_id)
);

CREATE TABLE IF NOT EXISTS world_state_version (
    state_version text PRIMARY KEY,
    physical_event_id text NOT NULL REFERENCES physical_event(physical_event_id),
    source_set_sha256 text NOT NULL CHECK (source_set_sha256 ~ '^sha256:[0-9a-f]{64}$'),
    canonical_state_sha256 text NOT NULL CHECK (canonical_state_sha256 ~ '^sha256:[0-9a-f]{64}$'),
    policy_version text NOT NULL,
    created_at timestamptz NOT NULL
);

CREATE TABLE IF NOT EXISTS model_analysis_run (
    analysis_run_id text PRIMARY KEY,
    state_version text NOT NULL REFERENCES world_state_version(state_version),
    model_name text NOT NULL,
    model_digest text NOT NULL,
    adapter_version text NOT NULL,
    prompt_sha256 text NOT NULL,
    configuration jsonb NOT NULL,
    created_at timestamptz NOT NULL
);

CREATE TABLE IF NOT EXISTS operator_action (
    action_id text PRIMARY KEY,
    operator_id text NOT NULL,
    decision text NOT NULL CHECK (decision IN ('reviewed','approved_bounded','rejected')),
    state_version text NOT NULL,
    rationale text NOT NULL,
    evidence_ids jsonb NOT NULL,
    policy_ids jsonb NOT NULL,
    reviewed_at timestamptz NOT NULL
);

CREATE TABLE IF NOT EXISTS audit_event (
    audit_id text PRIMARY KEY,
    event_type text NOT NULL,
    subject_id text NOT NULL,
    occurred_at timestamptz NOT NULL,
    evidence_ids jsonb NOT NULL,
    policy_ids jsonb NOT NULL,
    public_rationale text NOT NULL
);

CREATE TABLE IF NOT EXISTS outbox_event (
    outbox_id bigserial PRIMARY KEY,
    topic text NOT NULL,
    aggregate_id text NOT NULL,
    payload jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    delivered_at timestamptz
);
