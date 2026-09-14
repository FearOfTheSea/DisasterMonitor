ALTER TABLE imagery_jobs ADD COLUMN IF NOT EXISTS max_attempts integer NOT NULL DEFAULT 4;
ALTER TABLE imagery_jobs ADD COLUMN IF NOT EXISTS diagnostic text;
ALTER TABLE imagery_jobs DROP CONSTRAINT IF EXISTS imagery_jobs_max_attempts_check;
ALTER TABLE imagery_jobs ADD CONSTRAINT imagery_jobs_max_attempts_check
    CHECK (max_attempts BETWEEN 1 AND 10);
