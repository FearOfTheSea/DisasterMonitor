CREATE TABLE IF NOT EXISTS provider_budget_window (
    provider_id text NOT NULL,
    window_start timestamptz NOT NULL,
    reset_at timestamptz NOT NULL,
    limit_units integer NOT NULL CHECK (limit_units > 0),
    reserved_units integer NOT NULL DEFAULT 0 CHECK (reserved_units >= 0),
    settled_units integer NOT NULL DEFAULT 0 CHECK (settled_units >= 0),
    released_units integer NOT NULL DEFAULT 0 CHECK (released_units >= 0),
    PRIMARY KEY (provider_id, window_start)
);

CREATE TABLE IF NOT EXISTS provider_budget_reservation (
    reservation_id text PRIMARY KEY,
    provider_id text NOT NULL,
    worker_id text NOT NULL,
    window_start timestamptz NOT NULL,
    estimated_units integer NOT NULL CHECK (estimated_units > 0),
    status text NOT NULL CHECK (status IN ('reserved','settled','released')),
    reserved_at timestamptz NOT NULL,
    settled_at timestamptz,
    actual_units integer
);

CREATE INDEX IF NOT EXISTS provider_budget_window_reset_idx
    ON provider_budget_window(reset_at, provider_id);
