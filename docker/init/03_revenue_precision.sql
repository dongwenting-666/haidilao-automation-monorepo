-- Migration: Increase revenue precision from NUMERIC(12,2) to NUMERIC(15,5)
-- Reason: Raw target values have up to 5 significant decimal places (e.g. 116.04649253052)
-- This migration is idempotent: ALTER COLUMN TYPE to higher precision does not lose data.

DO $$
BEGIN
    -- Only run if the column is still NUMERIC(12,2)
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'store_targets'
          AND column_name = 'revenue'
          AND numeric_precision = 12
          AND numeric_scale = 2
    ) THEN
        ALTER TABLE store_targets ALTER COLUMN revenue TYPE NUMERIC(15,5);
        RAISE NOTICE 'store_targets.revenue precision upgraded to NUMERIC(15,5)';
    ELSE
        RAISE NOTICE 'store_targets.revenue already at correct precision, skipping';
    END IF;
END $$;
