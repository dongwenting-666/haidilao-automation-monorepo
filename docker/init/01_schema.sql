-- Automation targets per month per store
CREATE TABLE IF NOT EXISTS store_targets (
    id          SERIAL PRIMARY KEY,
    month_key   VARCHAR(7)    NOT NULL,         -- e.g. '2026-03'
    store_name  VARCHAR(64)   NOT NULL,
    revenue     NUMERIC(20,11) DEFAULT 0,
    tr_slot_1   NUMERIC(6,4)  DEFAULT 0,        -- 08:00-13:59
    tr_slot_2   NUMERIC(6,4)  DEFAULT 0,        -- 14:00-16:59
    tr_slot_3   NUMERIC(6,4)  DEFAULT 0,        -- 17:00-21:59
    tr_slot_4   NUMERIC(6,4)  DEFAULT 0,        -- 22:00-(次)07:59
    tr_total    NUMERIC(6,4)  DEFAULT 0,
    created_at  TIMESTAMPTZ   DEFAULT NOW(),
    updated_at  TIMESTAMPTZ   DEFAULT NOW(),
    UNIQUE (month_key, store_name)
);

-- Competitor (假想敌) mapping — store → benchmark store
CREATE TABLE IF NOT EXISTS store_competitors (
    id              SERIAL PRIMARY KEY,
    store_name      VARCHAR(64) NOT NULL UNIQUE,
    competitor_name VARCHAR(64) NOT NULL,
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);

-- Admin users — records everyone who attempts login via Lark OAuth
-- whitelisted=true means they can access the admin UI
CREATE TABLE IF NOT EXISTS admin_users (
    id            SERIAL PRIMARY KEY,
    open_id       VARCHAR(64)  NOT NULL UNIQUE,
    name          VARCHAR(128) NOT NULL,
    avatar_url    TEXT         DEFAULT '',
    whitelisted   BOOLEAN      DEFAULT false,
    first_seen_at TIMESTAMPTZ  DEFAULT NOW(),
    last_seen_at  TIMESTAMPTZ  DEFAULT NOW()
);
