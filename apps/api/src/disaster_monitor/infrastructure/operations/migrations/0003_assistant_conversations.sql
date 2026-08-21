CREATE TABLE IF NOT EXISTS conversation (
    conversation_id text PRIMARY KEY,
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL
);

CREATE TABLE IF NOT EXISTS conversation_message (
    message_id text PRIMARY KEY,
    conversation_id text NOT NULL REFERENCES conversation(conversation_id)
        ON DELETE CASCADE,
    role text NOT NULL CHECK (role IN ('user', 'assistant')),
    content text NOT NULL,
    created_at timestamptz NOT NULL
);

CREATE INDEX IF NOT EXISTS conversation_updated_idx
    ON conversation(updated_at DESC, conversation_id DESC);

CREATE INDEX IF NOT EXISTS conversation_message_time_idx
    ON conversation_message(conversation_id, created_at, message_id);
