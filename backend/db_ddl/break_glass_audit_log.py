"""T012: break_glass_audit_log DDL module.

Canonical DDL for the ``break_glass_audit_log`` table that records
emergency merge overrides (break-glass events).
"""


def get_break_glass_audit_log_sql() -> str:
    """Return the CREATE TABLE SQL for break_glass_audit_log."""
    return """
    CREATE TABLE IF NOT EXISTS break_glass_audit_log (
        id BIGSERIAL PRIMARY KEY,
        actor_id BIGINT NOT NULL,
        pr_id TEXT NOT NULL,
        gates_skipped JSONB NOT NULL,
        reason TEXT NOT NULL,
        secondary_reviewer_id BIGINT NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );

    CREATE INDEX IF NOT EXISTS idx_break_glass_audit_log_actor
        ON break_glass_audit_log (actor_id);
    CREATE INDEX IF NOT EXISTS idx_break_glass_audit_log_created
        ON break_glass_audit_log (created_at);
    """
