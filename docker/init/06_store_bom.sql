-- Per-store dish ↔ material BOM (replaces stale IPMS export — per 2026-05 audit
-- IPMS material codes had drifted from operations team's hand-curated recipes).
-- Each row is one (store × dish × spec × material) link. Materials are sourced
-- from MB5B / inventory; dishes are from POS sales reports.
CREATE TABLE IF NOT EXISTS store_bom (
    id               SERIAL PRIMARY KEY,
    werks            VARCHAR(8)    NOT NULL,         -- 'CA01' .. 'CA08'
    dish_code        BIGINT        NOT NULL,         -- 菜品编码 e.g. 1060061
    dish_name        VARCHAR(255),                   -- 菜品名称 (display)
    dish_short_code  BIGINT,                         -- 菜品短编码 (Sheet3 lookup key)
    spec             VARCHAR(32),                    -- '单锅' / '常温' / NULL
    material_code    BIGINT        NOT NULL,         -- 物料编码 / 物料号
    material_name    VARCHAR(255),                   -- 物料名称 (display)
    portion          NUMERIC(15,6),                  -- 单位物料用量 (N col)
    loss_factor      NUMERIC(10,4) DEFAULT 1.0,      -- 损耗 = 100/产成率
    unit             VARCHAR(16),                    -- 库存单位 (公斤 / 听 / 瓶)
    packaging_factor NUMERIC(15,6),                  -- 物料单位 P col (optional)
    notes            TEXT,
    created_at       TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    updated_at       TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    created_by       VARCHAR(128),
    -- A dish×spec can map to many materials and a material can map to many
    -- dish×specs. The uniqueness is per (store, dish, spec, material) so we
    -- never store duplicate links.
    UNIQUE (werks, dish_code, spec, material_code)
);

CREATE INDEX IF NOT EXISTS idx_store_bom_werks_dish
    ON store_bom (werks, dish_code);
CREATE INDEX IF NOT EXISTS idx_store_bom_werks_material
    ON store_bom (werks, material_code);
