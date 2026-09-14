ALTER TABLE ingest_job ADD COLUMN IF NOT EXISTS lease_expires_at timestamptz;
ALTER TABLE ingest_job ADD COLUMN IF NOT EXISTS fencing_token bigint NOT NULL DEFAULT 0;
ALTER TABLE ingest_job ADD COLUMN IF NOT EXISTS diagnostic text;
CREATE INDEX IF NOT EXISTS ingest_job_lease_idx
    ON ingest_job(status, lease_expires_at, scheduled_for, job_id);

ALTER TABLE provider_attempt ADD COLUMN IF NOT EXISTS published_at timestamptz;
ALTER TABLE provider_attempt ADD COLUMN IF NOT EXISTS parse_failure boolean NOT NULL DEFAULT false;
ALTER TABLE provider_attempt ADD COLUMN IF NOT EXISTS admission_failure boolean NOT NULL DEFAULT false;
ALTER TABLE provider_attempt ADD COLUMN IF NOT EXISTS truncated boolean NOT NULL DEFAULT false;
ALTER TABLE provider_attempt ADD COLUMN IF NOT EXISTS hazard text;
