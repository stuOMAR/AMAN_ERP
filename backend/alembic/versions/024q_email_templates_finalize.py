"""Email templates formalization.

Feature 024 — T081. Adds unique (tenant_id, code, locale).
"""
from alembic import op

revision = "024q_email_templates_finalize"
down_revision = "024p_notifications_queue"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Ensure columns exist (may already be present)
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'email_templates' AND column_name = 'version'
            ) THEN
                ALTER TABLE email_templates ADD COLUMN version INT DEFAULT 1;
            END IF;
        END $$;
    """)

    op.create_index(
        "uq_email_template_code_locale", "email_templates",
        ["tenant_id", "code", "locale"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("uq_email_template_code_locale", table_name="email_templates")
