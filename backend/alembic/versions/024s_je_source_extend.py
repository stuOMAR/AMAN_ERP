"""Extend JE source CHECK constraints with Feature 024 values.

Feature 024 — T006. Adds payroll_reverse, ticket_allowance,
service_invoice, service_invoice_reverse to the allowed source set.
"""
from alembic import op

revision = "024s_je_source_extend"
down_revision = "024r_approval_tokens"
branch_labels = None
depends_on = None

# Full valid set including new Feature 024 values
_VALID_SOURCES = (
    "sales", "purchase", "payroll", "treasury", "manufacturing",
    "manual", "recurring", "asset", "system",
    "expense", "settlement", "reversal", "intercompany",
    "intercompany_elimination", "subscription", "fx_revaluation",
    "revenue_recognition", "impairment", "ecl_provision", "nrv_test",
    "ifrs15_revenue", "lease", "tax", "provision", "pos",
    "shipment", "delivery", "payment",
    # Feature 024 additions
    "payroll_reverse", "ticket_allowance",
    "service_invoice", "service_invoice_reverse",
)
_SOURCE_EXPR = " | ".join(f"'{s}'" for s in _VALID_SOURCES)


def upgrade() -> None:
    op.execute(
        f"""
        -- Extend journal_entries.source CHECK
        ALTER TABLE journal_entries
            DROP CONSTRAINT IF EXISTS ck_je_source_valid;

        ALTER TABLE journal_entries
            ADD CONSTRAINT ck_je_source_valid
            CHECK (source IS NULL OR source IN ({_SOURCE_EXPR}));

        -- Extend invoices.source CHECK (if column exists)
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'invoices' AND column_name = 'source'
            ) THEN
                ALTER TABLE invoices
                    DROP CONSTRAINT IF EXISTS ck_invoice_source_valid;

                ALTER TABLE invoices
                    ADD CONSTRAINT ck_invoice_source_valid
                    CHECK (source IS NULL OR source IN ({_SOURCE_EXPR}));
            END IF;
        END $$;
        """
    )


def downgrade() -> None:
    # Revert to the 022g set (without Feature 024 values)
    _OLD_SOURCES = (
        "sales", "purchase", "payroll", "treasury", "manufacturing",
        "manual", "recurring", "asset", "system",
        "expense", "settlement", "reversal", "intercompany",
        "intercompany_elimination", "subscription", "fx_revaluation",
        "revenue_recognition", "impairment", "ecl_provision", "nrv_test",
        "ifrs15_revenue", "lease", "tax", "provision", "pos",
        "shipment", "delivery", "payment",
    )
    old_expr = " | ".join(f"'{s}'" for s in _OLD_SOURCES)
    op.execute(
        f"""
        ALTER TABLE journal_entries
            DROP CONSTRAINT IF EXISTS ck_je_source_valid;

        ALTER TABLE journal_entries
            ADD CONSTRAINT ck_je_source_valid
            CHECK (source IS NULL OR source IN ({old_expr}));

        ALTER TABLE invoices
            DROP CONSTRAINT IF EXISTS ck_invoice_source_valid;

        ALTER TABLE invoices
            ADD CONSTRAINT ck_invoice_source_valid
            CHECK (source IS NULL OR source IN ({old_expr}));
        """
    )
