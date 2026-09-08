CREATE TABLE IF NOT EXISTS incident_projection (
    projection_id text PRIMARY KEY,
    snapshot_version text NOT NULL UNIQUE,
    retrieved_at timestamptz NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    payload jsonb NOT NULL
);

CREATE INDEX IF NOT EXISTS incident_projection_retrieved_idx
    ON incident_projection(retrieved_at DESC, projection_id DESC);

CREATE OR REPLACE FUNCTION protect_incident_projection() RETURNS trigger AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'incident_projection rows are append-only';
    END IF;
    IF ROW(NEW.projection_id, NEW.snapshot_version, NEW.retrieved_at,
           NEW.created_at, NEW.payload)
       IS DISTINCT FROM
       ROW(OLD.projection_id, OLD.snapshot_version, OLD.retrieved_at,
           OLD.created_at, OLD.payload) THEN
        RAISE EXCEPTION 'incident_projection rows are immutable';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS incident_projection_append_only ON incident_projection;
CREATE TRIGGER incident_projection_append_only
BEFORE UPDATE OR DELETE ON incident_projection
FOR EACH ROW EXECUTE FUNCTION protect_incident_projection();
