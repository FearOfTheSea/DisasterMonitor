CREATE TABLE IF NOT EXISTS web_fetch_state (
    source_id text PRIMARY KEY,
    etag text,
    last_modified text,
    last_attempt_at timestamptz,
    last_success_at timestamptz,
    consecutive_failures integer NOT NULL DEFAULT 0 CHECK (consecutive_failures >= 0),
    circuit_open_until timestamptz
);

CREATE TABLE IF NOT EXISTS web_fetch_audit (
    audit_id text PRIMARY KEY,
    source_id text NOT NULL,
    requested_url text NOT NULL,
    attempted_at timestamptz NOT NULL,
    outcome text NOT NULL,
    status_code integer,
    bytes_received integer NOT NULL CHECK (bytes_received >= 0),
    response_sha256 text,
    error_code text
);

CREATE INDEX IF NOT EXISTS web_fetch_audit_source_time_idx
    ON web_fetch_audit(source_id, attempted_at DESC, audit_id DESC);

DROP TRIGGER IF EXISTS web_fetch_audit_append_only ON web_fetch_audit;
CREATE TRIGGER web_fetch_audit_append_only
BEFORE UPDATE OR DELETE ON web_fetch_audit
FOR EACH ROW EXECUTE FUNCTION protect_news_sensing_records();
