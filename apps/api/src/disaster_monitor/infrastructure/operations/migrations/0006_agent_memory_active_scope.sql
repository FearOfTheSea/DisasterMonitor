WITH ranked_active_memory AS (
    SELECT
        memory_id,
        first_value(memory_id) OVER (
            PARTITION BY conversation_id, physical_event_id
            ORDER BY confirmed_at DESC, memory_id DESC
        ) AS retained_memory_id,
        row_number() OVER (
            PARTITION BY conversation_id, physical_event_id
            ORDER BY confirmed_at DESC, memory_id DESC
        ) AS active_rank
    FROM agent_memory
    WHERE memory_type = 'physical_event_reference'
      AND lifecycle_status = 'active'
)
UPDATE agent_memory AS memory
SET lifecycle_status = 'superseded',
    superseded_by_memory_id = ranked.retained_memory_id
FROM ranked_active_memory AS ranked
WHERE memory.memory_id = ranked.memory_id
  AND ranked.active_rank > 1;

ALTER TABLE agent_memory
    ALTER CONSTRAINT agent_memory_superseded_by_memory_id_fkey
    DEFERRABLE INITIALLY DEFERRED;

CREATE UNIQUE INDEX agent_memory_active_physical_event_scope_idx
    ON agent_memory(conversation_id, physical_event_id)
    WHERE memory_type = 'physical_event_reference'
      AND lifecycle_status = 'active';
