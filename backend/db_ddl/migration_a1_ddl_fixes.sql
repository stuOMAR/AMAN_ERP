-- migration_a1_ddl_fixes.sql
-- Sync DDL with ORM models and fix hardcoded tax defaults.
-- Safe to run multiple times (all use IF NOT EXISTS / SET DEFAULT).

-- 3a. tax_rates.jurisdiction_code (exists in ORM, missing from DDL)
ALTER TABLE tax_rates
  ADD COLUMN IF NOT EXISTS jurisdiction_code VARCHAR(10) NULL;

-- 3b-c. wht_transactions: journal_entry_id + period_date (exist in ORM, missing from DDL)
ALTER TABLE wht_transactions
  ADD COLUMN IF NOT EXISTS journal_entry_id INTEGER NULL
    REFERENCES journal_entries(id) ON DELETE SET NULL,
  ADD COLUMN IF NOT EXISTS period_date DATE NULL;

-- 3d-e. tax_calendar: recurrence_pattern + status (exist in ORM, missing from DDL)
ALTER TABLE tax_calendar
  ADD COLUMN IF NOT EXISTS recurrence_pattern VARCHAR(20) NULL,
  ADD COLUMN IF NOT EXISTS status VARCHAR(20) NULL DEFAULT 'pending';

-- 4a. contract_items: change DEFAULT 15 → DEFAULT 0
ALTER TABLE contract_items
  ALTER COLUMN tax_rate SET DEFAULT 0;
