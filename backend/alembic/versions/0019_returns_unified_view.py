"""T6.6 — Unified returns view across sales_returns and pos_returns.

Revision: 0019_returns_unified_view
Revises: 0018_expense_reversal_columns
Create Date: 2026-05-01

Goal (T6.6 DoD): "استعلام واحد يعرض جميع المرتجعات" — a single query that
returns every return regardless of channel.

Implementation: a read-only ``returns_unified`` SQL VIEW that UNIONs:

* ``sales_returns`` (full sales-channel returns with parties / invoices /
  taxes / refund methods).
* ``pos_returns`` (point-of-sale refunds tied to ``pos_orders`` /
  ``pos_sessions`` / cashiers).

The view exposes a normalized column set (``source``, ``return_id``,
``return_number``, ``return_date``, ``party_id``, ``branch_id``,
``warehouse_id``, ``original_doc_id``, ``refund_amount``,
``refund_method``, ``status``, ``created_at``, ``created_by``).

This is **non-destructive**: both underlying tables are untouched, so
all existing endpoints continue to work. Reports and dashboards now have
a single canonical surface.

Idempotent: ``CREATE OR REPLACE VIEW`` and guarded by ``to_regclass`` on
both source tables (so the migration succeeds even on partially-bootstrapped
tenants where one of the tables does not yet exist).
"""

from alembic import op


revision = "0019_returns_unified_view"
down_revision = "0018_expense_reversal_columns"
branch_labels = None
depends_on = None


_VIEW_SQL = """
DO $$
BEGIN
    IF to_regclass('public.sales_returns') IS NOT NULL
       AND to_regclass('public.pos_returns') IS NOT NULL THEN
        -- Only create the view if returns_unified does not exist as a real table
        IF NOT EXISTS (
            SELECT 1 FROM pg_class c
            JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname = 'public' AND c.relname = 'returns_unified' AND c.relkind = 'r'
        ) THEN
            EXECUTE $VIEW$
            CREATE OR REPLACE VIEW returns_unified AS
            SELECT
                'sales'::text                                AS source,
                sr.id                                        AS return_id,
                sr.return_number                             AS return_number,
                sr.return_date::timestamp                    AS return_date,
                sr.party_id                                  AS party_id,
                sr.branch_id                                 AS branch_id,
                sr.warehouse_id                              AS warehouse_id,
                sr.invoice_id                                AS original_doc_id,
                COALESCE(sr.refund_amount, sr.total, 0)::numeric(18,4) AS refund_amount,
                sr.refund_method                             AS refund_method,
                sr.status                                    AS status,
                sr.notes                                     AS notes,
                sr.created_at                                AS created_at,
                sr.created_by::text                          AS created_by
            FROM sales_returns sr

            UNION ALL

            SELECT
                'pos'::text                                  AS source,
                pr.id                                        AS return_id,
                ('POS-RET-' || pr.id::text)                  AS return_number,
                pr.created_at                                AS return_date,
                NULL::integer                                AS party_id,
                NULL::integer                                AS branch_id,
                NULL::integer                                AS warehouse_id,
                pr.original_order_id                         AS original_doc_id,
                COALESCE(pr.refund_amount, 0)::numeric(18,4) AS refund_amount,
                pr.refund_method                             AS refund_method,
                'completed'::text                            AS status,
                pr.notes                                     AS notes,
                pr.created_at                                AS created_at,
                pr.created_by::text                          AS created_by
            FROM pos_returns pr;
            $VIEW$;
        END IF;
    END IF;
END $$;
"""


_DROP_VIEW_SQL = "DROP VIEW IF EXISTS returns_unified"


def upgrade() -> None:
    op.execute(_VIEW_SQL)


def downgrade() -> None:
    op.execute(_DROP_VIEW_SQL)
