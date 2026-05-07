-- ═══════════════════════════════════════════════════════════════════════════
-- Migration: Tax Rate Linking & Branch-Aware Tax System
-- Date: 2026-05-07
-- Description:
--   1. Enhances tax_rates table (is_default, legal_entity_id)
--   2. Creates tax_rate_history audit table
--   3. Adds tax_rate_id FK to ALL line tables (preserves existing tax_rate)
--   4. Verifies branch_tax_settings structure
--   5. Fixes products table (tax_rate DEFAULT NULL, adds tax_rate_id)
--
-- Safety: All columns are nullable with no NOT NULL constraints on existing
--         tables. No existing data is modified or deleted.
-- ═══════════════════════════════════════════════════════════════════════════


-- ─────────────────────────────────────────────────────────────────────────
-- 1. ENHANCE tax_rates TABLE
-- ─────────────────────────────────────────────────────────────────────────
-- Note: effective_from (line 2117), effective_to (line 2118),
--       country_code (line 2115) already exist in the DDL.
--       Only is_default and legal_entity_id are new.

ALTER TABLE tax_rates
    ADD COLUMN IF NOT EXISTS is_default BOOLEAN DEFAULT FALSE;

ALTER TABLE tax_rates
    ADD COLUMN IF NOT EXISTS legal_entity_id INTEGER;

-- Index for fast lookup by country + active + default
CREATE INDEX IF NOT EXISTS idx_tax_rates_country_active
    ON tax_rates(country_code, is_active, is_default);


-- ─────────────────────────────────────────────────────────────────────────
-- 2. CREATE tax_rate_history TABLE
-- ─────────────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS tax_rate_history (
    id              SERIAL PRIMARY KEY,
    tax_rate_id     INTEGER NOT NULL REFERENCES tax_rates(id) ON DELETE CASCADE,
    changed_by      INTEGER NOT NULL REFERENCES company_users(id),
    old_rate        DECIMAL(10, 4),
    new_rate        DECIMAL(10, 4),
    old_name        VARCHAR(255),
    new_name        VARCHAR(255),
    old_country     VARCHAR(5),
    new_country     VARCHAR(5),
    reason          TEXT,
    changed_at      TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_tax_rate_history_rate
    ON tax_rate_history(tax_rate_id);

CREATE INDEX IF NOT EXISTS idx_tax_rate_history_date
    ON tax_rate_history(changed_at);


-- ─────────────────────────────────────────────────────────────────────────
-- 3. ADD tax_rate_id FK TO ALL LINE TABLES
-- ─────────────────────────────────────────────────────────────────────────
-- Existing tax_rate columns are KEPT as frozen snapshots.
-- New tax_rate_id provides the FK reference to tax_rates.

-- 3.1 invoice_lines
ALTER TABLE invoice_lines
    ADD COLUMN IF NOT EXISTS tax_rate_id INTEGER REFERENCES tax_rates(id);

CREATE INDEX IF NOT EXISTS idx_invoice_lines_tax_rate
    ON invoice_lines(tax_rate_id);

-- 3.2 purchase_order_lines
ALTER TABLE purchase_order_lines
    ADD COLUMN IF NOT EXISTS tax_rate_id INTEGER REFERENCES tax_rates(id);

CREATE INDEX IF NOT EXISTS idx_purchase_order_lines_tax_rate
    ON purchase_order_lines(tax_rate_id);

-- 3.3 sales_quotation_lines
ALTER TABLE sales_quotation_lines
    ADD COLUMN IF NOT EXISTS tax_rate_id INTEGER REFERENCES tax_rates(id);

CREATE INDEX IF NOT EXISTS idx_sales_quotation_lines_tax_rate
    ON sales_quotation_lines(tax_rate_id);

-- 3.4 sales_order_lines
ALTER TABLE sales_order_lines
    ADD COLUMN IF NOT EXISTS tax_rate_id INTEGER REFERENCES tax_rates(id);

CREATE INDEX IF NOT EXISTS idx_sales_order_lines_tax_rate
    ON sales_order_lines(tax_rate_id);

-- 3.5 sales_return_lines
ALTER TABLE sales_return_lines
    ADD COLUMN IF NOT EXISTS tax_rate_id INTEGER REFERENCES tax_rates(id);

CREATE INDEX IF NOT EXISTS idx_sales_return_lines_tax_rate
    ON sales_return_lines(tax_rate_id);

-- 3.6 contract_items
ALTER TABLE contract_items
    ADD COLUMN IF NOT EXISTS tax_rate_id INTEGER REFERENCES tax_rates(id);

CREATE INDEX IF NOT EXISTS idx_contract_items_tax_rate
    ON contract_items(tax_rate_id);

-- 3.7 pos_order_lines
ALTER TABLE pos_order_lines
    ADD COLUMN IF NOT EXISTS tax_rate_id INTEGER REFERENCES tax_rates(id);

CREATE INDEX IF NOT EXISTS idx_pos_order_lines_tax_rate
    ON pos_order_lines(tax_rate_id);

-- 3.8 subscription_invoices
ALTER TABLE subscription_invoices
    ADD COLUMN IF NOT EXISTS tax_rate_id INTEGER REFERENCES tax_rates(id);

CREATE INDEX IF NOT EXISTS idx_subscription_invoices_tax_rate
    ON subscription_invoices(tax_rate_id);

-- 3.9 returns_unified_lines
ALTER TABLE returns_unified_lines
    ADD COLUMN IF NOT EXISTS tax_rate_id INTEGER REFERENCES tax_rates(id);

CREATE INDEX IF NOT EXISTS idx_returns_unified_lines_tax_rate
    ON returns_unified_lines(tax_rate_id);


-- ─────────────────────────────────────────────────────────────────────────
-- 4. VERIFY / FIX branch_tax_settings
-- ─────────────────────────────────────────────────────────────────────────
-- Existing columns (from DDL line 2184):
--   branch_id, tax_regime_id, is_registered, registration_number,
--   custom_rate, is_exempt, exemption_reason, exemption_certificate,
--   exemption_expiry, is_active
-- All required columns already exist. Index already exists (line 2219).

-- Ensure index exists (idempotent)
CREATE INDEX IF NOT EXISTS idx_branch_tax_settings_branch
    ON branch_tax_settings(branch_id);

CREATE INDEX IF NOT EXISTS idx_branch_tax_settings_regime
    ON branch_tax_settings(tax_regime_id);


-- ─────────────────────────────────────────────────────────────────────────
-- 5. FIX products TABLE
-- ─────────────────────────────────────────────────────────────────────────

-- 5.1 Change tax_rate DEFAULT from 15 to NULL
--     (existing rows keep their value, only new rows affected)
ALTER TABLE products
    ALTER COLUMN tax_rate DROP DEFAULT;

-- 5.2 Add tax_rate_id FK
ALTER TABLE products
    ADD COLUMN IF NOT EXISTS tax_rate_id INTEGER REFERENCES tax_rates(id);

CREATE INDEX IF NOT EXISTS idx_products_tax_rate
    ON products(tax_rate_id);


-- ═══════════════════════════════════════════════════════════════════════════
-- MIGRATION COMPLETE
-- ═══════════════════════════════════════════════════════════════════════════
-- Summary of changes:
--   • tax_rates: +is_default, +legal_entity_id, +index
--   • tax_rate_history: NEW table (audit trail)
--   • 9 line tables: +tax_rate_id FK (existing tax_rate kept as snapshot)
--   • branch_tax_settings: verified + indexes
--   • products: tax_rate DEFAULT changed to NULL, +tax_rate_id FK
-- ═══════════════════════════════════════════════════════════════════════════
