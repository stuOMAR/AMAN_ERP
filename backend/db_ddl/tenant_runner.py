"""T6.4 — Tenant schema runner.

Single orchestrator that applies the per-tenant CREATE TABLE / CREATE INDEX
DDL (defined in :mod:`db_ddl.tenant_schema`) to a freshly-provisioned tenant
database. This module replaces the bulk of the inline DDL that used to live
in ``backend/database.py``.

Public API:

* :func:`apply_tenant_schema` — execute every SQL block, then post-DDL
  fix-ups (indexes, ``updated_at`` trigger, idempotent CHECK constraints,
  cycle-breaking FKs). Idempotent: every statement uses ``IF NOT EXISTS``
  or is wrapped in a ``DO $$ ... EXISTS`` guard.

It is consumed by:

  1. :func:`database.create_company_tables` — fresh-tenant bootstrap.
  2. The Alembic baseline migration ``0001_baseline_complete`` — so that
     ``alembic upgrade head`` against an empty tenant DB creates the full
     schema, satisfying the T6.4 DoD.
"""
from __future__ import annotations

import logging
import re
from typing import Any

from sqlalchemy import text

from db_ddl.tenant_schema import (
    get_additional_base_tables_sql,
    get_additional_dependent_tables_sql,
    get_advanced_inventory_phase2_tables_sql,
    get_advanced_inventory_tables_sql,
    get_approval_tables_sql,
    get_cashflow_forecast_tables_sql,
    get_contract_tables_sql,
    get_core_dependent_tables_sql,
    get_costing_policy_tables_sql,
    get_currency_tables_sql,
    get_extended_features_tables_sql,
    get_financial_tables_sql,
    get_foundation_tables_sql,
    get_gl_integrity_guards_sql,
    get_manufacturing_tables_sql,
    get_organization_tables_sql,
    get_performance_indexes_sql,
    get_phase5_integration_tables_sql,
    get_phase_features_tables_sql,
    get_pos_tables_sql,
    get_security_tables_sql,
    get_system_completion_tables_sql,
    get_treasury_base_tables_sql,
    get_treasury_dependent_tables_sql,
    get_audit_security_finance_tables_sql,
    get_feature023_tables_sql,
    get_feature024_tables_sql,
    get_audit_h_ddl_sync_sql,
)

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────────
# SQL splitter — preserves $$/$tag$ blocks and SQL comments.
# ──────────────────────────────────────────────────────────────────────────

def split_sql_statements(sql_block: str) -> list[str]:
    """Split SQL preserving PostgreSQL ``$$...$$`` / ``$tag$...$tag$`` blocks
    and SQL comments. ``;`` inside a comment or quoted/dollar-quoted string
    does NOT terminate a statement.
    """
    statements: list[str] = []
    current: list[str] = []
    in_single_quote = False
    in_double_quote = False
    dollar_quote_tag: str | None = None
    i = 0
    n = len(sql_block)

    while i < n:
        char = sql_block[i]

        if dollar_quote_tag:
            if sql_block.startswith(dollar_quote_tag, i):
                current.append(dollar_quote_tag)
                i += len(dollar_quote_tag)
                dollar_quote_tag = None
                continue
            current.append(char)
            i += 1
            continue

        if not in_single_quote and not in_double_quote:
            if char == "-" and i + 1 < n and sql_block[i + 1] == "-":
                newline_idx = sql_block.find("\n", i)
                if newline_idx == -1:
                    current.append(sql_block[i:])
                    i = n
                else:
                    current.append(sql_block[i : newline_idx + 1])
                    i = newline_idx + 1
                continue
            if char == "/" and i + 1 < n and sql_block[i + 1] == "*":
                depth = 1
                j = i + 2
                while j < n and depth > 0:
                    if sql_block[j] == "/" and j + 1 < n and sql_block[j + 1] == "*":
                        depth += 1
                        j += 2
                        continue
                    if sql_block[j] == "*" and j + 1 < n and sql_block[j + 1] == "/":
                        depth -= 1
                        j += 2
                        continue
                    j += 1
                current.append(sql_block[i:j])
                i = j
                continue
            if char == "$":
                m = re.match(r"\$[A-Za-z0-9_]*\$", sql_block[i:])
                if m:
                    dollar_quote_tag = m.group(0)
                    current.append(dollar_quote_tag)
                    i += len(dollar_quote_tag)
                    continue

        if char == "'" and not in_double_quote:
            if in_single_quote and i + 1 < n and sql_block[i + 1] == "'":
                current.append("''")
                i += 2
                continue
            in_single_quote = not in_single_quote
            current.append(char)
            i += 1
            continue

        if char == '"' and not in_single_quote:
            in_double_quote = not in_double_quote
            current.append(char)
            i += 1
            continue

        if char == ";" and not in_single_quote and not in_double_quote:
            stmt = "".join(current).strip()
            if stmt:
                statements.append(stmt)
            current = []
            i += 1
            continue

        current.append(char)
        i += 1

    tail = "".join(current).strip()
    if tail:
        statements.append(tail)
    return statements


def _statement_kind(statement: str) -> str:
    stmt = statement.lstrip()
    while True:
        if stmt.startswith("--"):
            nl = stmt.find("\n")
            if nl == -1:
                stmt = ""
                break
            stmt = stmt[nl + 1 :].lstrip()
            continue
        if stmt.startswith("/*"):
            end = stmt.find("*/")
            if end == -1:
                break
            stmt = stmt[end + 2 :].lstrip()
            continue
        break
    upper = stmt.upper()
    if upper.startswith("CREATE TABLE"):
        return "CREATE TABLE"
    if re.match(r"^CREATE\s+(UNIQUE\s+)?INDEX\b", upper):
        return "CREATE INDEX"
    if upper.startswith("ALTER TABLE"):
        return "ALTER TABLE"
    if re.match(r"^CREATE\s+MATERIALIZED\s+VIEW\b", upper):
        return "CREATE MATERIALIZED VIEW"
    if upper.startswith("DO $$") or upper.startswith("DO $"):
        return "DO BLOCK"
    return "OTHER"


def _should_defer(statement: str, error: Exception) -> bool:
    kind = _statement_kind(statement)
    if kind not in ("CREATE TABLE", "CREATE INDEX", "ALTER TABLE", "CREATE MATERIALIZED VIEW", "DO BLOCK"):
        return False
    err_text = str(error)
    if "UndefinedTable" in err_text:
        return True
    if "UndefinedColumn" in err_text and kind in ("CREATE INDEX", "CREATE MATERIALIZED VIEW"):
        return True
    return False


def _ensure_fk_if_missing(
    conn: Any,
    table_name: str,
    column_name: str,
    referenced_table: str,
    constraint_name: str,
) -> None:
    """Add FK only when no FK already exists for the same (column, target)."""
    exists = conn.execute(
        text(
            """
            SELECT 1
            FROM information_schema.table_constraints tc
            JOIN information_schema.key_column_usage kcu
              ON tc.constraint_name = kcu.constraint_name
             AND tc.table_schema = kcu.table_schema
            JOIN information_schema.referential_constraints rc
              ON tc.constraint_name = rc.constraint_name
             AND tc.table_schema = rc.constraint_schema
            JOIN information_schema.constraint_column_usage ccu
              ON rc.unique_constraint_name = ccu.constraint_name
             AND rc.unique_constraint_schema = ccu.constraint_schema
            WHERE tc.constraint_type = 'FOREIGN KEY'
              AND tc.table_schema = current_schema()
              AND tc.table_name = :table_name
              AND kcu.column_name = :column_name
              AND ccu.table_name = :referenced_table
            LIMIT 1
            """
        ),
        {
            "table_name": table_name,
            "column_name": column_name,
            "referenced_table": referenced_table,
        },
    ).fetchone()
    if exists:
        return
    conn.execute(
        text(
            f"""
            ALTER TABLE {table_name}
            ADD CONSTRAINT {constraint_name}
            FOREIGN KEY ({column_name})
            REFERENCES {referenced_table}(id)
            ON DELETE SET NULL
            """
        )
    )


# ──────────────────────────────────────────────────────────────────────────
# DDL block ordering — preserved verbatim from legacy create_company_tables.
# ──────────────────────────────────────────────────────────────────────────

def _ordered_sql_blocks() -> list[str]:
    return [
        get_foundation_tables_sql(),               # 0  Foundation
        get_organization_tables_sql(),             # 1  Org / HR
        get_additional_base_tables_sql(),          # 2  Customers/Products/Inventory/RFQ
        get_treasury_base_tables_sql(),            # 3  Treasury base
        get_core_dependent_tables_sql(),           # 4  Journal lines, parties, invoices
        get_additional_dependent_tables_sql(),     # 5  PO/SO/SQ/SR/Vouchers/Commissions
        get_financial_tables_sql(),                # 6  Fiscal years/Payroll/Budgets/Assets/Tax/Projects
        get_treasury_dependent_tables_sql(),       # 7  Checks/Notes/Expenses
        get_currency_tables_sql(),                 # 8  Multi-currency
        get_pos_tables_sql(),                      # 9  POS
        get_contract_tables_sql(),                 # 10 Contracts
        get_costing_policy_tables_sql(),           # 11 Costing
        get_advanced_inventory_tables_sql(),       # 12 Adv Inv
        get_advanced_inventory_phase2_tables_sql(),# 13 Adv Inv Phase 2
        get_manufacturing_tables_sql(),            # 14 Manufacturing
        get_approval_tables_sql(),                 # 15 Approval Workflows
        get_security_tables_sql(),                 # 16 Security
        get_performance_indexes_sql(),             # 17 Performance indexes
        get_cashflow_forecast_tables_sql(),        # 18 Cash Flow Forecast
        get_phase_features_tables_sql(),           # 19 Matching/SSO/Costing/Intercompany
        get_system_completion_tables_sql(),        # 20 System completion
        get_extended_features_tables_sql(),        # 21 Extended features
        get_gl_integrity_guards_sql(),             # 22 GL integrity guards
        get_phase5_integration_tables_sql(),       # 23 Integration keys/retry/DLQ
        get_audit_security_finance_tables_sql(),   # 24 Feature 022 audit/security/finance
        get_feature023_tables_sql(),               # 25 Feature 023 sales/inventory/mfg
        get_feature024_tables_sql(),               # 26 Feature 024 workforce/service/comms
        get_audit_h_ddl_sync_sql(),                # 27 Audit H Batch 10 — DDL sync (F-NEW-019..022)
    ]


# ──────────────────────────────────────────────────────────────────────────
# Post-DDL fix-ups: indexes, trigger, CHECK constraints. All idempotent.
# ──────────────────────────────────────────────────────────────────────────

_POST_DDL_INDEXES: list[str] = [
    "CREATE INDEX IF NOT EXISTS idx_accounts_type ON accounts(account_type)",
    "CREATE INDEX IF NOT EXISTS idx_accounts_parent ON accounts(parent_id)",
    "CREATE INDEX IF NOT EXISTS idx_journal_entries_date ON journal_entries(entry_date)",
    "CREATE INDEX IF NOT EXISTS idx_journal_entries_status ON journal_entries(status)",
    "CREATE INDEX IF NOT EXISTS idx_journal_lines_account ON journal_lines(account_id)",
    "CREATE INDEX IF NOT EXISTS idx_journal_lines_entry ON journal_lines(journal_entry_id)",
    "CREATE INDEX IF NOT EXISTS idx_invoices_date ON invoices(invoice_date)",
    "CREATE INDEX IF NOT EXISTS idx_invoices_party ON invoices(party_id)",
    "CREATE INDEX IF NOT EXISTS idx_invoices_type_status ON invoices(invoice_type, status)",
    "CREATE INDEX IF NOT EXISTS idx_invoices_branch ON invoices(branch_id)",
    "CREATE INDEX IF NOT EXISTS idx_company_users_username ON company_users(username)",
    "CREATE INDEX IF NOT EXISTS idx_company_users_email ON company_users(email)",
    "CREATE INDEX IF NOT EXISTS idx_customers_code ON customers(customer_code)",
    "CREATE INDEX IF NOT EXISTS idx_suppliers_code ON suppliers(supplier_code)",
    "CREATE INDEX IF NOT EXISTS idx_products_code ON products(product_code)",
    "CREATE INDEX IF NOT EXISTS idx_products_barcode ON products(barcode)",
    "CREATE INDEX IF NOT EXISTS idx_inventory_product ON inventory(product_id)",
    "CREATE INDEX IF NOT EXISTS idx_inventory_warehouse ON inventory(warehouse_id)",
    "CREATE INDEX IF NOT EXISTS idx_inventory_product_warehouse ON inventory(product_id, warehouse_id)",
    "CREATE INDEX IF NOT EXISTS idx_inventory_txn_product ON inventory_transactions(product_id)",
    "CREATE INDEX IF NOT EXISTS idx_inventory_txn_date ON inventory_transactions(created_at)",
    "CREATE INDEX IF NOT EXISTS idx_inventory_txn_type ON inventory_transactions(transaction_type)",
    "CREATE INDEX IF NOT EXISTS idx_sales_orders_customer ON sales_orders(customer_id)",
    "CREATE INDEX IF NOT EXISTS idx_sales_orders_status ON sales_orders(status)",
    "CREATE INDEX IF NOT EXISTS idx_purchase_orders_supplier ON purchase_orders(supplier_id)",
    "CREATE INDEX IF NOT EXISTS idx_purchase_orders_status ON purchase_orders(status)",
    "CREATE INDEX IF NOT EXISTS idx_pos_orders_session ON pos_orders(session_id)",
    "CREATE INDEX IF NOT EXISTS idx_pos_orders_date ON pos_orders(order_date)",
    "CREATE INDEX IF NOT EXISTS idx_pos_sessions_status ON pos_sessions(status)",
    "CREATE INDEX IF NOT EXISTS idx_employees_department ON employees(department_id)",
    "CREATE INDEX IF NOT EXISTS idx_attendance_employee_date ON attendance(employee_id, date)",
    "CREATE INDEX IF NOT EXISTS idx_payroll_entries_period ON payroll_entries(period_id)",
    # T10.2 #175 — additional index coverage for hot read paths.
    "CREATE INDEX IF NOT EXISTS idx_attendance_date ON attendance(date)",
    "CREATE INDEX IF NOT EXISTS idx_payroll_entries_emp_period ON payroll_entries(employee_id, period_id)",
    "CREATE INDEX IF NOT EXISTS idx_pos_orders_customer_date ON pos_orders(customer_id, order_date)",
    # Partial index — only the unreconciled rows (the typical bank-rec hot set).
    "CREATE INDEX IF NOT EXISTS idx_journal_lines_unreconciled ON journal_lines(is_reconciled) WHERE is_reconciled = FALSE",
    "CREATE INDEX IF NOT EXISTS idx_treasury_txn_date ON treasury_transactions(transaction_date)",
    "CREATE INDEX IF NOT EXISTS idx_treasury_txn_treasury ON treasury_transactions(treasury_id)",
    "CREATE INDEX IF NOT EXISTS idx_party_txn_party ON party_transactions(party_id)",
    "CREATE INDEX IF NOT EXISTS idx_party_txn_date ON party_transactions(transaction_date)",
]


_UPDATED_AT_TRIGGER_FN = """
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ language 'plpgsql';
"""


_TRIGGER_TABLES: list[str] = [
    "company_users", "accounts", "customers", "suppliers", "products",
    "invoices", "journal_entries", "budgets", "assets", "employees",
    "employee_loans", "leave_requests", "projects", "project_tasks",
    "contracts", "sales_orders", "purchase_orders", "warehouses",
    "treasury_accounts", "tax_rates", "currencies", "parties",
    "sales_quotations", "expenses", "pos_sessions",
    "delivery_orders", "landed_costs", "print_templates",
]


_INV_MFG_CHECK_CONSTRAINTS_DO_BLOCK = """
DO $$
BEGIN
    IF to_regclass('public.inventory') IS NOT NULL
       AND NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ck_inventory_qty_nonneg') THEN
        BEGIN
            ALTER TABLE inventory
                ADD CONSTRAINT ck_inventory_qty_nonneg
                CHECK (quantity >= 0) NOT VALID;
        EXCEPTION WHEN others THEN
            RAISE NOTICE 'ck_inventory_qty_nonneg skipped: %', SQLERRM;
        END;
    END IF;

    IF to_regclass('public.inventory') IS NOT NULL
       AND NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ck_inventory_reserved_nonneg') THEN
        BEGIN
            ALTER TABLE inventory
                ADD CONSTRAINT ck_inventory_reserved_nonneg
                CHECK (reserved_quantity >= 0) NOT VALID;
        EXCEPTION WHEN others THEN
            RAISE NOTICE 'ck_inventory_reserved_nonneg skipped: %', SQLERRM;
        END;
    END IF;

    IF to_regclass('public.bom_components') IS NOT NULL
       AND NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ck_bom_components_waste_bounded') THEN
        BEGIN
            ALTER TABLE bom_components
                ADD CONSTRAINT ck_bom_components_waste_bounded
                CHECK (waste_percentage >= 0 AND waste_percentage <= 100) NOT VALID;
        EXCEPTION WHEN others THEN
            RAISE NOTICE 'ck_bom_components_waste_bounded skipped: %', SQLERRM;
        END;
    END IF;

    IF to_regclass('public.bom_components') IS NOT NULL
       AND NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ck_bom_components_costshare_bounded') THEN
        BEGIN
            ALTER TABLE bom_components
                ADD CONSTRAINT ck_bom_components_costshare_bounded
                CHECK (cost_share_percentage >= 0 AND cost_share_percentage <= 100) NOT VALID;
        EXCEPTION WHEN others THEN
            RAISE NOTICE 'ck_bom_components_costshare_bounded skipped: %', SQLERRM;
        END;
    END IF;
END $$;
"""


# T6.6: Unified returns view across sales_returns and pos_returns.
# Created in the post-DDL phase because it depends on both source tables.
# Mirrored by Alembic migration 0019_returns_unified_view for existing tenants.
_RETURNS_UNIFIED_VIEW_DO_BLOCK = """
DO $$
BEGIN
    IF to_regclass('public.sales_returns') IS NOT NULL
       AND to_regclass('public.pos_returns') IS NOT NULL THEN
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
END $$;
"""


# ---------------------------------------------------------------------------
# T7.1 + T7.6 — pg_trgm + GIN search indexes, and FK / lookup indexes.
# Public so alembic migration 0020_search_and_fk_indexes can re-use them.
# ---------------------------------------------------------------------------

# T10.2 #172/#173/#174 — Pin ON DELETE behaviour for employee-linked HR
# history tables. Deletion of an `employees` row must NOT silently destroy
# attendance / leave / payroll history (audit + payroll integrity). We
# rebuild each FK with `ON DELETE RESTRICT` if the existing constraint
# carries the default `NO ACTION` (PostgreSQL `confdeltype = 'a'`).
# Idempotent: skips when the FK already enforces RESTRICT (`'r'`),
# CASCADE (`'c'`), or SET NULL (`'n'`) intentionally.
_FK_ON_DELETE_GUARDS_DO_BLOCK = """
DO $fk_guards$
DECLARE
    rec RECORD;
    target_pairs TEXT[][] := ARRAY[
        ARRAY['attendance',      'employee_id', 'employees'],
        ARRAY['leave_requests',  'employee_id', 'employees'],
        ARRAY['payroll_entries', 'employee_id', 'employees']
    ];
    pair TEXT[];
    fk_name TEXT;
BEGIN
    FOREACH pair SLICE 1 IN ARRAY target_pairs
    LOOP
        IF to_regclass('public.' || pair[1]) IS NULL
           OR to_regclass('public.' || pair[3]) IS NULL THEN
            CONTINUE;
        END IF;

        FOR rec IN
            SELECT c.conname, c.confdeltype
            FROM pg_constraint c
            JOIN pg_class child ON child.oid = c.conrelid
            JOIN pg_attribute a ON a.attrelid = c.conrelid
                                AND a.attnum = ANY(c.conkey)
            JOIN pg_class parent ON parent.oid = c.confrelid
            WHERE c.contype = 'f'
              AND child.relname = pair[1]
              AND a.attname = pair[2]
              AND parent.relname = pair[3]
        LOOP
            -- Only rewrite if it's still the default NO ACTION.
            IF rec.confdeltype = 'a' THEN
                fk_name := rec.conname;
                BEGIN
                    EXECUTE format('ALTER TABLE %I DROP CONSTRAINT %I',
                                   pair[1], fk_name);
                    EXECUTE format(
                        'ALTER TABLE %I ADD CONSTRAINT %I '
                        'FOREIGN KEY (%I) REFERENCES %I(id) ON DELETE RESTRICT',
                        pair[1], fk_name, pair[2], pair[3]
                    );
                EXCEPTION WHEN OTHERS THEN
                    RAISE NOTICE 'fk guard % skipped: %', fk_name, SQLERRM;
                END;
            END IF;
        END LOOP;
    END LOOP;
END $fk_guards$;
"""


_PG_TRGM_EXTENSION_SQL = """
DO $$
BEGIN
    BEGIN
        EXECUTE 'CREATE EXTENSION IF NOT EXISTS pg_trgm';
    EXCEPTION WHEN insufficient_privilege THEN
        RAISE NOTICE 'pg_trgm: insufficient privilege; ask DBA to install';
    WHEN others THEN
        RAISE NOTICE 'pg_trgm install skipped: %', SQLERRM;
    END;
END $$;
"""


# T10.2 #151/#150 — extend opportunity_activities with the fields the audit
# flagged (outcome / duration_minutes / completed_at). The base table
# already has `completed BOOLEAN`, so the API exposes that as the
# ``is_completed`` flag. New columns are nullable so existing rows are
# unaffected. Idempotent ALTER … IF NOT EXISTS.
_OPPORTUNITY_ACTIVITIES_EXTEND_DO_BLOCK = """
DO $oppact_extend$
BEGIN
    IF to_regclass('public.opportunity_activities') IS NULL THEN
        RETURN;
    END IF;
    BEGIN
        ALTER TABLE opportunity_activities
            ADD COLUMN IF NOT EXISTS outcome VARCHAR(40),
            ADD COLUMN IF NOT EXISTS duration_minutes INTEGER,
            ADD COLUMN IF NOT EXISTS completed_at TIMESTAMPTZ;
    EXCEPTION WHEN OTHERS THEN
        RAISE NOTICE 'opportunity_activities extend skipped: %', SQLERRM;
    END;
END $oppact_extend$;
"""


# (table, column, index_name)
PHASE7_TRGM_INDEXES: list[tuple[str, str, str]] = [
    ("products", "product_name", "idx_products_name_trgm"),
    ("products", "product_code", "idx_products_code_trgm"),
    ("products", "barcode", "idx_products_barcode_trgm"),
    ("parties", "name", "idx_parties_name_trgm"),
    ("parties", "name_en", "idx_parties_name_en_trgm"),
    ("parties", "tax_number", "idx_parties_tax_trgm"),
    ("parties", "phone", "idx_parties_phone_trgm"),
    ("parties", "email", "idx_parties_email_trgm"),
    ("customers", "customer_name", "idx_customers_name_trgm"),
    ("customers", "customer_code", "idx_customers_code_trgm"),
    ("suppliers", "supplier_name", "idx_suppliers_name_trgm"),
    ("suppliers", "supplier_code", "idx_suppliers_code_trgm"),
    ("invoices", "invoice_number", "idx_invoices_number_trgm"),
    ("sales_orders", "so_number", "idx_sales_orders_number_trgm"),
    ("purchase_orders", "po_number", "idx_purchase_orders_number_trgm"),
]


PHASE7_FK_INDEXES: list[tuple[str, str, str]] = [
    # invoices
    ("invoices", "party_id", "idx_invoices_party"),
    ("invoices", "customer_id", "idx_invoices_customer"),
    ("invoices", "branch_id", "idx_invoices_branch"),
    ("invoices", "warehouse_id", "idx_invoices_warehouse"),
    ("invoices", "created_by", "idx_invoices_created_by"),
    ("invoice_lines", "invoice_id", "idx_invoice_lines_invoice"),
    ("invoice_lines", "product_id", "idx_invoice_lines_product"),
    # sales / purchase docs
    ("sales_orders", "party_id", "idx_sales_orders_party"),
    ("sales_orders", "customer_id", "idx_sales_orders_customer"),
    ("sales_orders", "branch_id", "idx_sales_orders_branch"),
    ("sales_order_lines", "order_id", "idx_sales_order_lines_order"),
    ("sales_order_lines", "product_id", "idx_sales_order_lines_product"),
    ("purchase_orders", "party_id", "idx_purchase_orders_party"),
    ("purchase_orders", "supplier_id", "idx_purchase_orders_supplier"),
    ("purchase_orders", "branch_id", "idx_purchase_orders_branch"),
    ("purchase_order_lines", "order_id", "idx_purchase_order_lines_order"),
    ("purchase_order_lines", "product_id", "idx_purchase_order_lines_product"),
    # returns
    ("sales_returns", "party_id", "idx_sales_returns_party"),
    ("sales_returns", "invoice_id", "idx_sales_returns_invoice"),
    ("sales_returns", "branch_id", "idx_sales_returns_branch"),
    ("sales_return_lines", "return_id", "idx_sales_return_lines_return"),
    ("sales_return_lines", "product_id", "idx_sales_return_lines_product"),
    # parties / customers / suppliers
    ("parties", "party_group_id", "idx_parties_group"),
    ("parties", "price_list_id", "idx_parties_price_list"),
    ("customers", "group_id", "idx_customers_group"),
    ("customers", "price_list_id", "idx_customers_price_list"),
    ("suppliers", "group_id", "idx_suppliers_group"),
    # inventory
    ("inventory", "product_id", "idx_inventory_product"),
    ("inventory", "warehouse_id", "idx_inventory_warehouse"),
    ("inventory_transactions", "product_id", "idx_inv_tx_product"),
    ("inventory_transactions", "warehouse_id", "idx_inv_tx_warehouse"),
    ("inventory_transactions", "reference_id", "idx_inv_tx_reference"),
    ("stock_adjustments", "warehouse_id", "idx_stock_adj_warehouse"),
    ("stock_adjustments", "branch_id", "idx_stock_adj_branch"),
    # treasury / payments
    ("treasury_transactions", "treasury_account_id", "idx_treas_tx_account"),
    ("treasury_transactions", "branch_id", "idx_treas_tx_branch"),
    ("payments", "party_id", "idx_payments_party"),
    ("payments", "treasury_account_id", "idx_payments_treasury"),
    ("payments", "invoice_id", "idx_payments_invoice"),
    ("payments", "branch_id", "idx_payments_branch"),
    ("receipts", "party_id", "idx_receipts_party"),
    ("receipts", "treasury_account_id", "idx_receipts_treasury"),
    ("receipts", "invoice_id", "idx_receipts_invoice"),
    ("receipts", "branch_id", "idx_receipts_branch"),
    ("payment_vouchers", "party_id", "idx_pv_party"),
    ("payment_vouchers", "branch_id", "idx_pv_branch"),
    ("payment_allocations", "voucher_id", "idx_pa_voucher"),
    ("payment_allocations", "invoice_id", "idx_pa_invoice"),
    # journal
    ("journal_lines", "entry_id", "idx_jl_entry"),
    ("journal_lines", "account_id", "idx_jl_account"),
    ("journal_lines", "cost_center_id", "idx_jl_cost_center"),
    ("journal_entries", "branch_id", "idx_je_branch"),
    ("journal_entries", "fiscal_period_id", "idx_je_fiscal_period"),
    # HR
    ("employees", "department_id", "idx_employees_department"),
    ("employees", "branch_id", "idx_employees_branch"),
    ("employees", "position_id", "idx_employees_position"),
    ("attendance", "employee_id", "idx_attendance_employee"),
    ("payroll_entries", "employee_id", "idx_payroll_entries_employee"),
    ("payroll_entries", "period_id", "idx_payroll_entries_period"),
    ("leave_requests", "employee_id", "idx_leave_requests_employee"),
    # audit
    ("audit_logs", "user_id", "idx_audit_logs_user"),
    ("audit_logs", "branch_id", "idx_audit_logs_branch"),
]


def _trgm_index_sql(table: str, column: str, idx_name: str) -> str:
    """Idempotent + column-existence-guarded GIN trigram index."""
    return f"""
    DO $$
    BEGIN
        IF to_regclass('public.{table}') IS NOT NULL
           AND EXISTS (
               SELECT 1 FROM information_schema.columns
               WHERE table_schema = 'public'
                 AND table_name   = '{table}'
                 AND column_name  = '{column}'
           ) THEN
            BEGIN
                EXECUTE 'CREATE INDEX IF NOT EXISTS {idx_name} ON {table} '
                        'USING gin ({column} gin_trgm_ops)';
            EXCEPTION WHEN others THEN
                RAISE NOTICE '{idx_name} skipped: %', SQLERRM;
            END;
        END IF;
    END $$;
    """


def _fk_index_sql(table: str, column: str, idx_name: str) -> str:
    """Idempotent + column-existence-guarded B-tree index on a FK column."""
    return f"""
    DO $$
    BEGIN
        IF to_regclass('public.{table}') IS NOT NULL
           AND EXISTS (
               SELECT 1 FROM information_schema.columns
               WHERE table_schema = 'public'
                 AND table_name   = '{table}'
                 AND column_name  = '{column}'
           ) THEN
            BEGIN
                EXECUTE 'CREATE INDEX IF NOT EXISTS {idx_name} ON {table}({column})';
            EXCEPTION WHEN others THEN
                RAISE NOTICE '{idx_name} skipped: %', SQLERRM;
            END;
        END IF;
    END $$;
    """


# T7.3 — phone_clean generated columns. (table, src_col, gen_col, idx_name)
PHASE7_PHONE_CLEAN_TARGETS: list[tuple[str, str, str, str]] = [
    ("parties", "phone", "phone_clean", "idx_parties_phone_clean"),
    ("customers", "phone", "phone_clean", "idx_customers_phone_clean"),
    ("suppliers", "phone", "phone_clean", "idx_suppliers_phone_clean"),
]


def _phone_clean_sql(table: str, src: str, gen: str, idx: str) -> str:
    """Adds a STORED generated column stripping non-digits + B-tree index."""
    return f"""
    DO $$
    BEGIN
        IF to_regclass('public.{table}') IS NULL THEN
            RETURN;
        END IF;
        IF NOT EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_schema='public' AND table_name='{table}' AND column_name='{src}'
        ) THEN
            RETURN;
        END IF;
        IF NOT EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_schema='public' AND table_name='{table}' AND column_name='{gen}'
        ) THEN
            BEGIN
                EXECUTE 'ALTER TABLE {table} ADD COLUMN {gen} text '
                        'GENERATED ALWAYS AS '
                        '(regexp_replace(coalesce({src},''''), ''\\D'', '''', ''g'')) STORED';
            EXCEPTION WHEN others THEN
                RAISE NOTICE '{table}.{gen} add-column skipped: %', SQLERRM;
                RETURN;
            END;
        END IF;
        BEGIN
            EXECUTE 'CREATE INDEX IF NOT EXISTS {idx} ON {table}({gen})';
        EXCEPTION WHEN others THEN
            RAISE NOTICE '{idx} skipped: %', SQLERRM;
        END;
    END $$;
    """


# T7.2 — search_vector tsvector columns + GIN indexes for unified search.
# (table, [source_columns], gen_col, idx_name)
PHASE7_SEARCH_VECTORS: list[tuple[str, list[str], str, str]] = [
    ("parties", ["name", "name_en", "tax_number", "phone", "email"],
     "search_vector", "idx_parties_search_vec"),
    ("products", ["product_name", "product_code", "barcode"],
     "search_vector", "idx_products_search_vec"),
    ("invoices", ["invoice_number", "notes"],
     "search_vector", "idx_invoices_search_vec"),
    ("sales_orders", ["so_number", "notes"],
     "search_vector", "idx_sales_orders_search_vec"),
    ("purchase_orders", ["po_number", "notes"],
     "search_vector", "idx_purchase_orders_search_vec"),
]


def _search_vector_sql(table: str, cols: list[str], gen: str, idx: str) -> str:
    """STORED tsvector generated column + GIN index for unified search.

    Uses the ``simple`` text-search configuration (case-fold + tokenise
    without stemming), which works well for Arabic source text.
    """
    parts = " || '' '' || ".join(f"coalesce({c},'''')" for c in cols)
    expr = f"to_tsvector(''simple'', {parts})"
    cols_check = " AND ".join(
        f"EXISTS (SELECT 1 FROM information_schema.columns "
        f"WHERE table_schema='public' AND table_name='{table}' AND column_name='{c}')"
        for c in cols
    )
    return f"""
    DO $$
    BEGIN
        IF to_regclass('public.{table}') IS NULL THEN
            RETURN;
        END IF;
        IF NOT ({cols_check}) THEN
            RETURN;
        END IF;
        IF NOT EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_schema='public' AND table_name='{table}' AND column_name='{gen}'
        ) THEN
            BEGIN
                EXECUTE 'ALTER TABLE {table} ADD COLUMN {gen} tsvector '
                        'GENERATED ALWAYS AS ({expr}) STORED';
            EXCEPTION WHEN others THEN
                RAISE NOTICE '{table}.{gen} skipped: %', SQLERRM;
                RETURN;
            END;
        END IF;
        BEGIN
            EXECUTE 'CREATE INDEX IF NOT EXISTS {idx} ON {table} USING gin({gen})';
        EXCEPTION WHEN others THEN
            RAISE NOTICE '{idx} skipped: %', SQLERRM;
        END;
    END $$;
    """


def apply_tenant_schema(conn: Any, currency: str = "SAR") -> None:
    """Apply the full tenant DDL to ``conn`` (a SQLAlchemy connection).

    The connection MUST be in AUTOCOMMIT mode (or the caller must commit
    afterwards). This function is idempotent: every CREATE uses
    ``IF NOT EXISTS`` and every constraint is wrapped in a guard.

    Steps:
      1. Execute each ordered SQL block, deferring statements that fail
         only due to unresolved table/column dependencies and retrying
         until convergence.
      2. Add cycle-breaking FKs (``customer_groups.price_list_id``,
         ``departments.manager_id``).
      3. Create the named index list (best-effort).
      4. Install the ``updated_at`` trigger function and apply it to all
         tables that carry an ``updated_at`` column.
      5. Add INV-F2 / MFG-F2 CHECK constraints idempotently.
    """
    blocks = _ordered_sql_blocks()
    deferred: list[tuple[int, int, str, str]] = []

    for block_idx, sql_block in enumerate(blocks):
        processed = sql_block.replace("'SAR'", f"'{currency}'")
        statements = split_sql_statements(processed)
        logger.info(f"Executing SQL block {block_idx} ({len(statements)} statements)")
        for stmt_idx, stmt in enumerate(statements):
            try:
                conn.execute(text(stmt + ";"))
            except Exception as e:
                if _should_defer(stmt, e):
                    deferred.append((block_idx, stmt_idx, stmt, str(e)))
                    logger.warning(
                        f"Deferring statement {stmt_idx} in block {block_idx}: unresolved dependency"
                    )
                    continue
                logger.error(f"Failed at statement {stmt_idx} in block {block_idx}: {stmt[:120]}")
                logger.error(f"Error: {e}")
                raise

    retry_round = 1
    while deferred:
        logger.info(f"Retrying deferred DDL, pass {retry_round} ({len(deferred)} statements)")
        remaining: list[tuple[int, int, str, str]] = []
        progress = False
        for block_idx, stmt_idx, stmt, _last_err in deferred:
            try:
                conn.execute(text(stmt + ";"))
                progress = True
            except Exception as e:
                if _should_defer(stmt, e):
                    remaining.append((block_idx, stmt_idx, stmt, str(e)))
                    continue
                logger.error(
                    f"Failed at deferred statement {stmt_idx} in block {block_idx}: {stmt[:120]}"
                )
                raise
        if not remaining:
            break
        if not progress:
            unresolved = [
                item for item in remaining
                if _statement_kind(item[2]) not in ("CREATE INDEX", "CREATE MATERIALIZED VIEW")
            ]
            if unresolved:
                b, i_, s, err = unresolved[0]
                raise RuntimeError(
                    f"Unresolved table dependency after retries (block={b}, statement={i_}): "
                    f"{s[:120]} | last_error={err[:200]}"
                )
            for b, i_, s, _e in remaining:
                logger.warning(
                    f"Skipping unresolved index/MV due to missing dependency "
                    f"(block={b}, statement={i_}): {s[:120]}"
                )
            break
        deferred = remaining
        retry_round += 1

    # Cycle-breaking FKs
    _ensure_fk_if_missing(
        conn, "customer_groups", "price_list_id", "customer_price_lists",
        "fk_customer_groups_price_list_id",
    )
    _ensure_fk_if_missing(
        conn, "departments", "manager_id", "employees",
        "fk_departments_manager_id",
    )

    # Best-effort named indexes
    for idx_sql in _POST_DDL_INDEXES:
        try:
            conn.execute(text(idx_sql))
        except Exception:
            pass

    # updated_at trigger function + per-table triggers
    conn.execute(text(_UPDATED_AT_TRIGGER_FN))
    for tbl in _TRIGGER_TABLES:
        try:
            has_col = conn.execute(text(
                "SELECT 1 FROM information_schema.columns "
                "WHERE table_name = :tbl AND column_name = 'updated_at'"
            ), {"tbl": tbl}).scalar()
            if not has_col:
                continue
            conn.execute(text(
                f"DROP TRIGGER IF EXISTS trigger_update_{tbl}_updated_at ON {tbl}; "
                f"CREATE TRIGGER trigger_update_{tbl}_updated_at "
                f"BEFORE UPDATE ON {tbl} "
                f"FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();"
            ))
        except Exception:
            pass

    # INV-F2 / MFG-F2 CHECK constraints (idempotent)
    try:
        conn.execute(text(_INV_MFG_CHECK_CONSTRAINTS_DO_BLOCK))
    except Exception as e:
        logger.warning(f"CHECK constraints (INV-F2/MFG-F2) skipped: {e}")

    # T6.6: unified returns view (sales_returns ∪ pos_returns), idempotent
    try:
        conn.execute(text(_RETURNS_UNIFIED_VIEW_DO_BLOCK))
    except Exception as e:
        logger.warning(f"returns_unified view skipped: {e}")

    # T10.2 #172/#173/#174 — pin ON DELETE RESTRICT on HR-history FKs.
    try:
        conn.execute(text(_FK_ON_DELETE_GUARDS_DO_BLOCK))
    except Exception as e:
        logger.warning(f"FK ON DELETE guards skipped: {e}")

    # T10.2 #150/#151 — opportunity_activities outcome/duration/completed_at.
    try:
        conn.execute(text(_OPPORTUNITY_ACTIVITIES_EXTEND_DO_BLOCK))
    except Exception as e:
        logger.warning(f"opportunity_activities extend skipped: {e}")

    # T7.1 + T7.6: pg_trgm extension, GIN trigram search indexes, and missing
    # FK/lookup indexes. The same lists are imported by alembic migration
    # 0020 so existing tenants get them via ``alembic upgrade head``.
    try:
        conn.execute(text(_PG_TRGM_EXTENSION_SQL))
    except Exception as e:
        logger.warning(f"pg_trgm extension skipped: {e}")
    for table, column, idx in PHASE7_TRGM_INDEXES:
        try:
            conn.execute(text(_trgm_index_sql(table, column, idx)))
        except Exception as e:
            logger.warning(f"trgm index {idx} skipped: {e}")
    for table, column, idx in PHASE7_FK_INDEXES:
        try:
            conn.execute(text(_fk_index_sql(table, column, idx)))
        except Exception as e:
            logger.warning(f"fk index {idx} skipped: {e}")

    # T7.3: phone_clean generated column + B-tree index for fast duplicate
    # detection. Same definitions used by alembic migration 0021.
    for table, src, gen, idx in PHASE7_PHONE_CLEAN_TARGETS:
        try:
            conn.execute(text(_phone_clean_sql(table, src, gen, idx)))
        except Exception as e:
            logger.warning(f"{table}.{gen} skipped: {e}")

    # T7.2: search_vector tsvector columns + GIN indexes for unified search.
    # Same definitions used by alembic migration 0022.
    for table, cols, gen, idx in PHASE7_SEARCH_VECTORS:
        try:
            conn.execute(text(_search_vector_sql(table, cols, gen, idx)))
        except Exception as e:
            logger.warning(f"{table}.{gen} (tsvector) skipped: {e}")
