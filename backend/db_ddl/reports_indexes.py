"""T101/T102: BRIN + composite indexes DDL module.

Canonical DDL for the additive indexes on audit_logs, journal_lines,
journal_entries, and inventory_transactions.
"""


def get_reports_indexes_sql() -> str:
    """Return the CREATE INDEX SQL for report performance indexes."""
    return """
    -- ═══════════════════════════════════════════════════════════════════
    -- BRIN indexes (append-mostly time-series columns)
    -- ═══════════════════════════════════════════════════════════════════
    CREATE INDEX IF NOT EXISTS idx_audit_logs_created_at_brin
        ON audit_logs USING BRIN (created_at);

    CREATE INDEX IF NOT EXISTS idx_journal_lines_posting_date_brin
        ON journal_lines USING BRIN (posting_date);

    CREATE INDEX IF NOT EXISTS idx_inventory_transactions_date_brin
        ON inventory_transactions USING BRIN (transaction_date);

    -- ═══════════════════════════════════════════════════════════════════
    -- Composite B-tree indexes (join paths)
    -- ═══════════════════════════════════════════════════════════════════
    CREATE INDEX IF NOT EXISTS idx_journal_lines_tenant_account_date
        ON journal_lines (tenant_id, account_id, posting_date);

    CREATE INDEX IF NOT EXISTS idx_journal_entries_tenant_source
        ON journal_entries (tenant_id, source, source_id);

    CREATE INDEX IF NOT EXISTS idx_inventory_transactions_tenant_item_date
        ON inventory_transactions (tenant_id, item_id, transaction_date);
    """
