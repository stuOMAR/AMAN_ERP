"""T7.3 — phone_clean generated column on parties + index.

Revision: 0021_phone_clean_column
Revises: 0020_search_and_fk_indexes
Create Date: 2026-05-01

Adds a stored generated column ``phone_clean`` on ``parties`` that strips
all non-digit characters from ``phone``. A B-tree index on it enables
sub-100ms duplicate-detection queries on 100K+ rows:

    SELECT party_id FROM parties WHERE phone_clean = :digits;

The column is also added to ``customers`` and ``suppliers`` if those
tables exist and contain a ``phone`` column.

Notes
-----
* ``GENERATED ALWAYS AS ... STORED`` requires PostgreSQL >= 12. The
  expression ``regexp_replace(coalesce(phone,''), '\\D', '', 'g')`` is
  IMMUTABLE, which PG requires for stored generated columns.
* Idempotent via ``IF NOT EXISTS`` (PG 13+) and a guarded DO block for
  the column itself (PG 12 lacks ``ADD COLUMN IF NOT EXISTS`` for
  generated columns in some patch versions, so we DO-block-guard it).
"""

from alembic import op


revision = "0021_phone_clean_column"
down_revision = "0020_search_and_fk_indexes"
branch_labels = None
depends_on = None


_TARGETS = [
    ("parties", "phone", "phone_clean", "idx_parties_phone_clean"),
    ("customers", "phone", "phone_clean", "idx_customers_phone_clean"),
    ("suppliers", "phone", "phone_clean", "idx_suppliers_phone_clean"),
]


def _add_phone_clean_sql(table: str, src: str, gen: str, idx: str) -> str:
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
                RAISE NOTICE '{table}.{gen} skipped: %', SQLERRM;
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


def _drop_phone_clean_sql(table: str, gen: str, idx: str) -> str:
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
    for table, src, gen, idx in _TARGETS:
        op.execute(_add_phone_clean_sql(table, src, gen, idx))


def downgrade() -> None:
    for table, _, gen, idx in _TARGETS:
        op.execute(_drop_phone_clean_sql(table, gen, idx))
