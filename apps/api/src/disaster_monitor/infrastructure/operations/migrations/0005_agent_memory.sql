CREATE TABLE IF NOT EXISTS agent_memory (
    memory_id text PRIMARY KEY,
    schema_version text NOT NULL,
    memory_type text NOT NULL CHECK (
        memory_type IN ('conversation_context', 'physical_event_reference')
    ),
    lifecycle_status text NOT NULL CHECK (
        lifecycle_status IN ('active', 'superseded', 'expired', 'deleted')
    ),
    summary text NOT NULL CHECK (
        char_length(summary) BETWEEN 1 AND 500
    ),
    conversation_id text NOT NULL REFERENCES conversation(conversation_id)
        ON DELETE CASCADE,
    physical_event_id text,
    disaster_identifier text,
    country_code char(3),
    source_message_ids jsonb NOT NULL CHECK (
        jsonb_typeof(source_message_ids) = 'array'
    ),
    evidence_ids jsonb NOT NULL CHECK (jsonb_typeof(evidence_ids) = 'array'),
    world_state_version text,
    created_at timestamptz NOT NULL,
    confirmed_at timestamptz NOT NULL,
    expires_at timestamptz,
    superseded_by_memory_id text REFERENCES agent_memory(memory_id),
    deleted_at timestamptz,
    authority text NOT NULL DEFAULT 'historical_context' CHECK (
        authority = 'historical_context'
    ),
    may_satisfy_current_evidence boolean NOT NULL DEFAULT false CHECK (
        may_satisfy_current_evidence = false
    ),
    CHECK (
        memory_type <> 'physical_event_reference'
        OR (
            physical_event_id IS NOT NULL
            AND disaster_identifier IS NOT NULL
            AND country_code IS NOT NULL
            AND world_state_version IS NOT NULL
            AND jsonb_array_length(evidence_ids) > 0
        )
    ),
    CHECK (
        (lifecycle_status = 'active'
         AND superseded_by_memory_id IS NULL AND deleted_at IS NULL)
        OR (lifecycle_status = 'superseded'
            AND superseded_by_memory_id IS NOT NULL AND deleted_at IS NULL)
        OR (lifecycle_status = 'expired'
            AND expires_at IS NOT NULL AND deleted_at IS NULL)
        OR (lifecycle_status = 'deleted' AND deleted_at IS NOT NULL)
    )
);

CREATE INDEX IF NOT EXISTS agent_memory_conversation_recall_idx
    ON agent_memory(conversation_id, lifecycle_status, confirmed_at DESC, memory_id);

CREATE INDEX IF NOT EXISTS agent_memory_event_recall_idx
    ON agent_memory(
        conversation_id, physical_event_id, lifecycle_status,
        confirmed_at DESC, memory_id
    );
