-- API keys for per-user authentication to server HTTP endpoints.
-- Each key is scoped (comma-separated): runs:trigger, reports:read, files:read, admin:*
-- Keys are tied to an admin_users.open_id for auditing.

CREATE TABLE IF NOT EXISTS api_keys (
    id          SERIAL PRIMARY KEY,
    key_hash    VARCHAR(64)   NOT NULL UNIQUE,   -- SHA-256 hash of the raw key (never store raw)
    key_prefix  VARCHAR(12)   NOT NULL,          -- first 8 chars of raw key for display (hld_xxxx...)
    open_id     VARCHAR(64)   NOT NULL REFERENCES admin_users(open_id),
    label       VARCHAR(128)  NOT NULL DEFAULT '',  -- human-readable label ("Hongming's laptop")
    scopes      TEXT          NOT NULL DEFAULT '',  -- comma-separated: runs:trigger,reports:read,...
    created_at  TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    last_used_at TIMESTAMPTZ,
    revoked_at  TIMESTAMPTZ                       -- NULL = active, set = revoked
);

CREATE INDEX IF NOT EXISTS idx_api_keys_key_hash ON api_keys (key_hash) WHERE revoked_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_api_keys_open_id ON api_keys (open_id);
