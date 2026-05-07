"""Auto-approve expenses below threshold.

Scheduled job that scans pending expense approvals and auto-approves
those below ``company_settings.expenses.auto_approve_threshold``.

Each auto-approval writes an audit row with ``critical=False``.
"""
from __future__ import annotations

import logging
from decimal import Decimal

from sqlalchemy import text

logger = logging.getLogger(__name__)


def _iter_tenant_engines():
    from database import _get_all_company_db_names
    from services.scheduler import _get_company_engine_for_db

    for db_name in _get_all_company_db_names():
        try:
            yield db_name, _get_company_engine_for_db(db_name)
        except Exception:
            logger.exception("[auto-approve] could not open engine for %s", db_name)


def _auto_approve_for_tenant(conn, tenant_id: str) -> int:
    """Auto-approve pending expenses below threshold. Returns count approved."""
    # Read threshold
    row = conn.execute(text(
        "SELECT setting_value FROM company_settings "
        "WHERE setting_key = 'expenses.auto_approve_threshold'"
    )).fetchone()
    if not row or not row[0]:
        return 0
    threshold = Decimal(str(row[0]))
    if threshold <= 0:
        return 0

    # Find pending expenses below threshold
    pending = conn.execute(text("""
        SELECT id, employee_id, amount, description
          FROM expenses
         WHERE approval_status = 'pending'
           AND amount < :threshold
         ORDER BY id
         LIMIT 200
    """), {"threshold": str(threshold)}).fetchall()

    count = 0
    for exp in pending:
        conn.execute(text("""
            UPDATE expenses
               SET approval_status = 'approved',
                   approved_by = 0,
                   approved_at = now(),
                   updated_at = now()
             WHERE id = :eid AND approval_status = 'pending'
        """), {"eid": exp.id})

        # Audit
        try:
            from services.audit_writer import log_activity
            log_activity(
                conn,
                action="expense.auto_approved",
                entity_type="expense",
                entity_id=exp.id,
                actor_id=None,
                details={
                    "amount": str(exp.amount),
                    "threshold": str(threshold),
                    "employee_id": exp.employee_id,
                },
                critical=False,
            )
        except Exception:
            logger.debug("Audit log for auto-approved expense %s skipped", exp.id)

        count += 1

    return count


def run_auto_approve() -> dict:
    """Run auto-approve across all tenants. Returns summary."""
    summary: dict[str, int] = {}

    for db_name, engine in _iter_tenant_engines():
        company_id = db_name.replace("aman_", "", 1)
        try:
            with engine.begin() as conn:
                count = _auto_approve_for_tenant(conn, company_id)
                if count > 0:
                    summary[company_id] = count
                    logger.info("[auto-approve][%s] %d expense(s) auto-approved", company_id, count)
        except Exception:
            logger.exception("[auto-approve] tenant %s failed", company_id)

    return summary


__all__ = ["run_auto_approve"]
