"""025c: Repair report classifier and materialized-view schema.

Revision: 025c_reports_schema_repair
Revises: 025b_kpi_tables
Create Date: 2026-05-02

Some local tenant databases were stamped at the Feature 025 head without
the Feature 022 account classification table or the Feature 025 report
materialized views. This migration is idempotent and aligns the tenant DB
with the schema used by the report services.
"""
from alembic import op


revision = "025c_reports_schema_repair"
down_revision = "025b_kpi_tables"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS account_classifications (
            id BIGSERIAL PRIMARY KEY,
            tenant_id BIGINT NOT NULL,
            account_id BIGINT NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
            statement_category VARCHAR(32) NOT NULL,
            sign SMALLINT NOT NULL,
            aggregation_hint VARCHAR(64),
            is_active BOOLEAN NOT NULL DEFAULT true,
            valid_from DATE NOT NULL DEFAULT CURRENT_DATE,
            valid_to DATE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
        );

        CREATE UNIQUE INDEX IF NOT EXISTS ux_account_classifications_active
            ON account_classifications (tenant_id, account_id)
            WHERE is_active = true;

        CREATE INDEX IF NOT EXISTS ix_account_classifications_lookup
            ON account_classifications (tenant_id, account_id, valid_from DESC)
            WHERE is_active = true;

        WITH ctx AS (
            SELECT CASE
                WHEN current_database() ~ '^aman_[0-9]+$'
                THEN regexp_replace(current_database(), '^aman_', '')::bigint
                ELSE 0
            END AS tenant_id
        )
        INSERT INTO account_classifications
            (tenant_id, account_id, statement_category, sign, aggregation_hint, is_active, valid_from)
        SELECT
            ctx.tenant_id,
            a.id,
            CASE LEFT(COALESCE(NULLIF(a.account_code::text, ''), NULLIF(a.account_number::text, ''), '1'), 1)
                WHEN '1' THEN 'asset'
                WHEN '2' THEN 'liability'
                WHEN '3' THEN 'equity'
                WHEN '4' THEN 'revenue'
                WHEN '5' THEN 'expense'
                ELSE 'asset'
            END,
            CASE LEFT(COALESCE(NULLIF(a.account_code::text, ''), NULLIF(a.account_number::text, ''), '1'), 1)
                WHEN '1' THEN 1
                WHEN '2' THEN -1
                WHEN '3' THEN -1
                WHEN '4' THEN -1
                WHEN '5' THEN 1
                ELSE 1
            END,
            'seed',
            true,
            CURRENT_DATE
        FROM accounts a
        CROSS JOIN ctx
        WHERE NOT EXISTS (
            SELECT 1
            FROM account_classifications ac
            WHERE ac.tenant_id = ctx.tenant_id
              AND ac.account_id = a.id
              AND ac.is_active = true
        );

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
        JOIN journal_entries je ON je.id = jl.journal_entry_id
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
        JOIN journal_entries je ON je.id = jl.journal_entry_id
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
    )


def downgrade() -> None:
    op.execute(
        """
        DROP INDEX IF EXISTS idx_mv_period_stats_unique;
        DROP MATERIALIZED VIEW IF EXISTS mv_period_stats;
        DROP INDEX IF EXISTS idx_mv_daily_financial_chart_unique;
        DROP MATERIALIZED VIEW IF EXISTS mv_daily_financial_chart;
        DROP INDEX IF EXISTS ix_account_classifications_lookup;
        """
    )