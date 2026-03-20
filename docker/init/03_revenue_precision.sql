-- Migration: Increase revenue precision from NUMERIC(12,2) to NUMERIC(20,11)
-- Reason: Raw target values have up to 11 significant decimal places (e.g. 116.04649253052)
-- This migration is idempotent: ALTER COLUMN TYPE to higher precision does not lose data.

DO $$
BEGIN
    -- Upgrade if column is NUMERIC(12,2) or NUMERIC(15,5) (previous intermediate migration)
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'store_targets'
          AND column_name = 'revenue'
          AND numeric_precision < 20
    ) THEN
        ALTER TABLE store_targets ALTER COLUMN revenue TYPE NUMERIC(20,11);
        RAISE NOTICE 'store_targets.revenue precision upgraded to NUMERIC(20,11)';
    ELSE
        RAISE NOTICE 'store_targets.revenue already at correct precision, skipping';
    END IF;
END $$;
