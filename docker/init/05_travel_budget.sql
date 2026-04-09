-- Travel budget targets per store per year
-- Used by the travel-expense-budget report to compute budget allocations
CREATE TABLE IF NOT EXISTS travel_budget_targets (
    id                SERIAL PRIMARY KEY,
    store_name        VARCHAR(64)    NOT NULL,
    year              INTEGER        NOT NULL,
    target_revenue    NUMERIC(20,2)  DEFAULT 0,    -- 26年目标收入 (USD)
    prev_year_revenue NUMERIC(20,2)  DEFAULT 0,    -- 25年收入 (USD)
    prev_year_travel  NUMERIC(20,2)  DEFAULT 0,    -- 25年差旅费 (USD, verified manual data)
    q1_revenue        NUMERIC(20,2)  DEFAULT 0,    -- 26年Q1实际收入 (USD)
    cad_to_usd_rate   NUMERIC(10,6)  DEFAULT 0.695265, -- CAD→USD conversion rate
    created_at        TIMESTAMPTZ    DEFAULT NOW(),
    updated_at        TIMESTAMPTZ    DEFAULT NOW(),
    UNIQUE (store_name, year)
);
