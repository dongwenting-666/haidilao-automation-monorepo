-- Admin users — records everyone who has attempted login via Lark OAuth.
-- Whitelist is managed here; ADMIN_WHITELIST env var is the bootstrap fallback.
CREATE TABLE IF NOT EXISTS admin_users (
    id            SERIAL PRIMARY KEY,
    open_id       VARCHAR(64)  NOT NULL UNIQUE,
    name          VARCHAR(128) NOT NULL,
    avatar_url    VARCHAR(512) DEFAULT '',
    whitelisted   BOOLEAN      NOT NULL DEFAULT FALSE,
    first_seen_at TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    last_seen_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);
