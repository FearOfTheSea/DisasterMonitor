ALTER TABLE conversation_message
    ADD COLUMN IF NOT EXISTS assistant_payload jsonb;
