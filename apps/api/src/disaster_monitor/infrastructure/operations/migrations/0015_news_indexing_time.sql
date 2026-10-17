-- Publication is unknown for indexing-only leads. Preserve the distinct clock.
ALTER TABLE news_observation ALTER COLUMN published_at DROP NOT NULL;
ALTER TABLE news_observation ADD COLUMN IF NOT EXISTS indexed_at timestamptz;
