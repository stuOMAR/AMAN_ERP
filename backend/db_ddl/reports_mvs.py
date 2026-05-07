"""T100: Reports materialized views DDL module.

Canonical DDL for ``mv_daily_financial_chart`` and ``mv_period_stats``.
"""


def get_reports_mvs_sql() -> str:
    """Return the CREATE MATERIALIZED VIEW SQL for reports MVs."""
    return """
    -- ═══════════════════════════════════════════════════════════════════
    -- MV: mv_daily_financial_chart
    -- Per-day revenue / expense / cash position per tenant + company
    -- ═══════════════════════════════════════════════════════════════════
    CREATE MATERIALIZED VIEW IF NOT EXISTS mv_daily_financial_chart AS
    SELECT
           CASE WHEN current_database() ~ '^aman_[0-9]+$'
               THEN regexp_replace(current_database(), '^aman_', '')::bigint
               ELSE 0 END AS tenant_id,
           CASE WHEN current_database() ~ '^aman_[0-9]+$'
               THEN regexp_replace(current_database(), '^aman_', '')::bigint
               ELSE 0 END AS company_id,
           je.entry_date::date AS date,
           COALESCE(SUM(CASE WHEN ac.statement_category IN ('revenue', 'contra_revenue') THEN jl.credit - jl.debit ELSE 0 END), 0) AS revenue,
           COALESCE(SUM(CASE WHEN ac.statement_category IN ('expense', 'contra_expense') THEN jl.debit - jl.credit ELSE 0 END), 0) AS expense,
        COALESCE(SUM(jl.debit - jl.credit), 0) AS cash_position,
        NOW() AS refreshed_at
    FROM journal_lines jl
    JOIN journal_entries je ON je.id = jl.journal_entry_id AND je.status = 'posted'
        LEFT JOIN account_classifications ac
         ON ac.account_id = jl.account_id
         AND ac.tenant_id = CASE WHEN current_database() ~ '^aman_[0-9]+$'
                                                         THEN regexp_replace(current_database(), '^aman_', '')::bigint
                                                         ELSE 0 END
        AND ac.is_active = true
        AND ac.valid_from <= CURRENT_DATE
        AND (ac.valid_to IS NULL OR ac.valid_to >= CURRENT_DATE)
        GROUP BY 1, 2, 3;

    CREATE UNIQUE INDEX IF NOT EXISTS idx_mv_daily_financial_chart_unique
        ON mv_daily_financial_chart (tenant_id, company_id, date);

    -- ═══════════════════════════════════════════════════════════════════
    -- MV: mv_period_stats
    -- Per-period totals replacing per-request calculate_period_stats
    -- ═══════════════════════════════════════════════════════════════════
    CREATE MATERIALIZED VIEW IF NOT EXISTS mv_period_stats AS
    SELECT
                CASE WHEN current_database() ~ '^aman_[0-9]+$'
                         THEN regexp_replace(current_database(), '^aman_', '')::bigint
                         ELSE 0 END AS tenant_id,
                CASE WHEN current_database() ~ '^aman_[0-9]+$'
                         THEN regexp_replace(current_database(), '^aman_', '')::bigint
                         ELSE 0 END AS company_id,
        p.id AS period_id,
        p.start_date AS period_start,
        p.end_date AS period_end,
                COALESCE(SUM(CASE WHEN ac.statement_category IN ('revenue', 'contra_revenue') THEN jl.credit - jl.debit ELSE 0 END), 0) AS revenue,
                COALESCE(SUM(CASE WHEN ac.statement_category IN ('expense', 'contra_expense') THEN jl.debit - jl.credit ELSE 0 END), 0) AS expense,
                COALESCE(SUM(CASE WHEN ac.statement_category IN ('revenue', 'contra_revenue') THEN jl.credit - jl.debit ELSE 0 END), 0)
                    - COALESCE(SUM(CASE WHEN ac.statement_category IN ('expense', 'contra_expense') THEN jl.debit - jl.credit ELSE 0 END), 0) AS gross_profit,
        0 AS operating_margin,
                COALESCE(SUM(CASE WHEN ac.statement_category = 'asset' THEN jl.debit ELSE 0 END), 0) AS cash_in,
                COALESCE(SUM(CASE WHEN ac.statement_category = 'asset' THEN jl.credit ELSE 0 END), 0) AS cash_out,
        NOW() AS refreshed_at
    FROM journal_lines jl
    JOIN journal_entries je ON je.id = jl.journal_entry_id AND je.status = 'posted'
        JOIN fiscal_periods p ON je.entry_date::date BETWEEN p.start_date AND p.end_date
        LEFT JOIN account_classifications ac
            ON ac.account_id = jl.account_id
         AND ac.tenant_id = CASE WHEN current_database() ~ '^aman_[0-9]+$'
                                                         THEN regexp_replace(current_database(), '^aman_', '')::bigint
                                                         ELSE 0 END
         AND ac.is_active = true
         AND ac.valid_from <= CURRENT_DATE
         AND (ac.valid_to IS NULL OR ac.valid_to >= CURRENT_DATE)
        GROUP BY 1, 2, p.id, p.start_date, p.end_date;

    CREATE UNIQUE INDEX IF NOT EXISTS idx_mv_period_stats_unique
        ON mv_period_stats (tenant_id, company_id, period_id);
    """
