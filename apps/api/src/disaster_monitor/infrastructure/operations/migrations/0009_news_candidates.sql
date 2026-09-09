CREATE TABLE IF NOT EXISTS news_observation (
    observation_id text PRIMARY KEY,
    source_id text NOT NULL,
    external_id text NOT NULL,
    publisher text NOT NULL,
    title text NOT NULL,
    canonical_url text NOT NULL,
    published_at timestamptz NOT NULL,
    updated_at timestamptz,
    observed_at timestamptz NOT NULL
);

CREATE INDEX IF NOT EXISTS news_observation_published_idx
    ON news_observation(published_at DESC, observation_id DESC);

CREATE TABLE IF NOT EXISTS incident_candidate_revision (
    revision_id text PRIMARY KEY,
    candidate_id text NOT NULL,
    disaster text NOT NULL,
    location text NOT NULL,
    event_time timestamptz NOT NULL,
    status text NOT NULL,
    sources jsonb NOT NULL,
    news_break_at timestamptz NOT NULL,
    first_observed_at timestamptz NOT NULL,
    candidate_created_at timestamptz NOT NULL,
    verified_at timestamptz,
    rejected_at timestamptz
);

CREATE INDEX IF NOT EXISTS incident_candidate_current_idx
    ON incident_candidate_revision(candidate_id, candidate_created_at DESC, revision_id DESC);
CREATE INDEX IF NOT EXISTS incident_candidate_news_break_idx
    ON incident_candidate_revision(news_break_at DESC);

CREATE OR REPLACE FUNCTION protect_news_sensing_records() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION '% rows are append-only', TG_TABLE_NAME;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS news_observation_append_only ON news_observation;
CREATE TRIGGER news_observation_append_only
BEFORE UPDATE OR DELETE ON news_observation
FOR EACH ROW EXECUTE FUNCTION protect_news_sensing_records();

DROP TRIGGER IF EXISTS incident_candidate_revision_append_only ON incident_candidate_revision;
CREATE TRIGGER incident_candidate_revision_append_only
BEFORE UPDATE OR DELETE ON incident_candidate_revision
FOR EACH ROW EXECUTE FUNCTION protect_news_sensing_records();
