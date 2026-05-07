-- Migration: Add is_exempt column to products table
-- Date: 2026-05-07
-- Description: Allows marking individual products as tax-exempt

ALTER TABLE products
    ADD COLUMN IF NOT EXISTS is_exempt BOOLEAN DEFAULT FALSE;

-- Also ensure tax_rate_id exists (in case migration_tax_rate_linking.sql wasn't applied)
ALTER TABLE products
    ADD COLUMN IF NOT EXISTS tax_rate_id INTEGER REFERENCES tax_rates(id);

CREATE INDEX IF NOT EXISTS idx_products_tax_rate ON products(tax_rate_id);
