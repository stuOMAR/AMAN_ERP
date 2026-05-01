"""T7.2 — search_vector (tsvector) GENERATED columns + GIN indexes.

Revision: 0022_unified_search_vectors
Revises: 0021_phone_clean_column
Create Date: 2026-05-01

Adds a STORED ``search_vector tsvector`` column to the five entities most
commonly queried by the unified ``GET /search`` endpoint (T7.2):

* parties        — name, name_en, tax_number, phone, email
* products       — product_name, product_code, barcode
* invoices       — invoice_number, notes
* sales_orders   — so_number, notes
* purchase_orders — po_number, notes

Using ``GENERATED ALWAYS AS (...) STORED`` keeps the column synchronized
with its source columns automatically — no triggers required (PG 12+).
We use the ``simple`` configuration because it dictionary-normalises case
without stemming, which works well for Arabic text. Each tsvector is
also paired with a GIN index for sub-200ms searches.

Idempotent and column-existence-guarded; safe to re-run.
"""

from alembic import op


revision = "0022_unified_search_vectors"
down_revision = "0021_phone_clean_column"
branch_labels = None
depends_on = None


# (table, [source_columns], gen_col, idx_name)
_TARGETS: list[tuple[str, list[str], str, str]] = [
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


def _expr(cols: list[str]) -> str:
    """Build ``to_tsvector('simple', coalesce(c1,'') || ' ' || coalesce(c2,'') ...)``."""
    parts = " || '' '' || ".join(f"coalesce({c},'''')" for c in cols)
    return f"to_tsvector(''simple'', {parts})"


def _add_sql(table: str, cols: list[str], gen: str, idx: str) -> str:
    expr = _expr(cols)
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


def _drop_sql(table: str, gen: str, idx: str) -> str:
    return f"""
    DO $$
    BEGIN
        IF to_regclass('public.{table}') IS NULL THEN
            RETURN;
        END IF;
        EXECUTE 'DROP INDEX IF EXISTS {idx}';
        IF EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_schema='public' AND table_name='{table}' AND column_name='{gen}'
        ) THEN
            EXECUTE 'ALTER TABLE {table} DROP COLUMN {gen}';
        END IF;
    END $$;
    """


def upgrade() -> None:
    for table, cols, gen, idx in _TARGETS:
        op.execute(_add_sql(table, cols, gen, idx))


def downgrade() -> None:
    for table, _, gen, idx in _TARGETS:
        op.execute(_drop_sql(table, gen, idx))
