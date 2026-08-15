CREATE OR REPLACE FUNCTION protect_source_snapshot() RETURNS trigger AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'source_snapshot rows are append-only';
    END IF;
    IF ROW(NEW.snapshot_id, NEW.idempotency_key, NEW.source_id,
           NEW.canonical_request_identity, NEW.provider_revision, NEW.retrieved_at,
           NEW.published_at, NEW.observed_at, NEW.response_status, NEW.content_type,
           NEW.payload_sha256, NEW.payload_size_bytes, NEW.blob_uri, NEW.rights_id)
       IS DISTINCT FROM
       ROW(OLD.snapshot_id, OLD.idempotency_key, OLD.source_id,
           OLD.canonical_request_identity, OLD.provider_revision, OLD.retrieved_at,
           OLD.published_at, OLD.observed_at, OLD.response_status, OLD.content_type,
           OLD.payload_sha256, OLD.payload_size_bytes, OLD.blob_uri, OLD.rights_id) THEN
        RAISE EXCEPTION 'immutable source_snapshot fields cannot change';
    END IF;
    IF OLD.content_deleted_at IS NOT NULL AND
       ROW(NEW.content_deleted_at, NEW.content_deletion_reason) IS DISTINCT FROM
       ROW(OLD.content_deleted_at, OLD.content_deletion_reason) THEN
        RAISE EXCEPTION 'source_snapshot tombstones cannot change';
    END IF;
    IF (NEW.content_deleted_at IS NULL) <> (NEW.content_deletion_reason IS NULL) THEN
        RAISE EXCEPTION 'source_snapshot tombstones require time and reason';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
