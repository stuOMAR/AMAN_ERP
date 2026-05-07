-- migration_b1_tax_groups.sql
-- Activate multi-tax per line via tax_groups and applied_taxes JSONB.
-- Safe to run multiple times (all use IF NOT EXISTS).

-- Step 2: Add tax_group_id to products
ALTER TABLE products
  ADD COLUMN IF NOT EXISTS tax_group_id INTEGER
    REFERENCES tax_groups(id) ON DELETE SET NULL;

-- Step 4: Add applied_taxes JSONB to all line tables
-- Format: [{"tax_rate_id":3,"tax_rate":15,"tax_name":"VAT","tax_code":"VAT-SA-15"}, ...]

ALTER TABLE invoice_lines
  ADD COLUMN IF NOT EXISTS applied_taxes JSONB NULL;

ALTER TABLE sales_order_lines
  ADD COLUMN IF NOT EXISTS applied_taxes JSONB NULL;

ALTER TABLE purchase_order_lines
  ADD COLUMN IF NOT EXISTS applied_taxes JSONB NULL;

ALTER TABLE pos_order_lines
  ADD COLUMN IF NOT EXISTS applied_taxes JSONB NULL;

ALTER TABLE sales_quotation_lines
  ADD COLUMN IF NOT EXISTS applied_taxes JSONB NULL;

ALTER TABLE sales_return_lines
  ADD COLUMN IF NOT EXISTS applied_taxes JSONB NULL;

ALTER TABLE contract_items
  ADD COLUMN IF NOT EXISTS applied_taxes JSONB NULL;
